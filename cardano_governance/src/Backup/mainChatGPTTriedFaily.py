import httpx 
import os
import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from masumi_crewai.config import Config
from masumi_crewai.payment import Payment, Amount
from types import MethodType
import hashlib
import json

from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Request, Query
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import httpx

# --- Import your Crew ---
# Import the @CrewBase class from the refactored crew.py
try:
    # Assumes main.py and crew.py are in the same directory (src)
    from crew import CardanoGovernanceCrew # Direct import
except ImportError as e:
    # Fallback if running uvicorn from one level above src
    try:
         from src.crew import CardanoGovernanceCrew
    except ImportError:
         # Log the error clearly if import fails from both locations
         logging.error(f"Failed to import CardanoGovernanceCrew from crew.py or src.crew.py. Error: {e}")
         # Set to None so the server can potentially start but background tasks will fail informatively
         CardanoGovernanceCrew = None


# --- Load Environment Variables ---
# Load .env file from the current directory (src)
# Ensure this runs before the Crew is potentially instantiated if it needs env vars on init
load_dotenv()

# --- Masumi Payment Configuration (from .env) ---
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:3001/api/v1")
PAYMENT_API_KEY = os.getenv("PAYMENT_API_KEY")
AGENT_IDENTIFIER = os.getenv("AGENT_IDENTIFIER")
PAYMENT_AMOUNT = int(os.getenv("PAYMENT_AMOUNT", "10000000"))
PAYMENT_UNIT = os.getenv("PAYMENT_UNIT", "lovelace")
SELLER_VKEY = os.getenv("SELLER_VKEY")

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Cardano Governance Crew Agent (Masumi Integrated)",
    description="Agent using @CrewBase structure.",
    version="1.2.0" # Incremented version
)

# --- In-Memory Job Store ---
# IMPORTANT: Replace with a persistent store (Redis, DB) for production
jobs = {}
payment_instances = {}

# --- Initialize Masumi Payment Config ---
# Check if necessary keys are present before initializing
config = None
if not all([PAYMENT_SERVICE_URL, PAYMENT_API_KEY]):
    logger.error("MASUMI_PAYMENT_SERVICE_URL or MASUMI_PAYMENT_API_KEY missing from environment. Masumi features disabled.")
    config = None # Indicate config failed
else:
    try:
        config = Config(
            payment_service_url=PAYMENT_SERVICE_URL,
            payment_api_key=PAYMENT_API_KEY
        )
        logger.info("Masumi Payment Config Initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Masumi Config: {e}")
        config = None

# --- Pydantic Models for API ---
#class JobInput(BaseModel):
    # Define inputs expected by the crew's kickoff method
    # These should match the variables used in your task descriptions (e.g., {topic})
    #topic: str = Field(..., example="Analyze latest governance proposals")
    # Add other inputs if your tasks use them, e.g.:
    # max_proposals: Optional[int] = Field(default=1, example=1)

class StartJobRequest(BaseModel):
    # The crew expects 'topic' based on original main.py
    topic: str = Field(..., example="Analyze Catalyst Fund12 proposals")

class JobStatus(BaseModel):
    job_id: str
    status: str
    payment_status: Optional[str] = None # Added payment status
    message: Optional[str] = None

class JobResult(JobStatus):
    result: Optional[Any] = None

class Availability(BaseModel):
    status: str = "available"
    message: Optional[str] = None

class FixedPayment(Payment):
    def __init__(self, *args, **kwargs):
        # satisfy the base class __init__
        kwargs.setdefault("amounts", [])
        super().__init__(*args, **kwargs)

    async def create_payment_request(self):
        # Manually POST /payment with RequestedFunds=null
        body = {
            "agentIdentifier":         self.agent_identifier,
            "network":                 self.network,
            "RequestedFunds":          None,
            "paymentType":             self.payment_type,
            "identifierFromPurchaser": self.identifier_from_purchaser,
            "inputHash":               self.input_hash,
        }
        headers = {"Authorization": f"Bearer {self.config.payment_api_key}"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.config.payment_service_url}/payment",
                headers=headers,
                json=body
            )
            resp.raise_for_status()
            return resp.json()


# --- Task Function ---
async def execute_crew_task(inputs: dict) -> str:
    """ Executes the CardanoGovernanceCrew task """
    logger.info(f"Executing Crew task with inputs: {inputs}")
    if CardanoGovernanceCrew is None:
        logger.error("CardanoGovernanceCrew not imported. Cannot execute task.")
        raise ValueError("Crew class not available.") # Raise error to handle in callback
    try:
        crew_instance = CardanoGovernanceCrew()
        result = crew_instance.crew().kickoff(inputs=inputs)
        logger.info("Crew task kickoff completed.")
        return str(result)
    except Exception as e:
        logger.error(f"Error during Crew task execution: {e}", exc_info=True)
        # Return error string to be stored in job result
        return f"Error executing crew task: {e}"


# --- New Payment Callback Handler ---
async def handle_payment_status(job_id: str, payment_id: str) -> None:
    """ Executes CrewAI task after payment confirmation via SDK callback """
    if job_id not in jobs:
        logger.error(f"Job {job_id} not found for payment callback {payment_id}.")
        if job_id in payment_instances: # Clean up dangling monitor if job is gone
            payment_instances[job_id].stop_status_monitoring()
            del payment_instances[job_id]
        return

    # Avoid processing callback multiple times for the same job if status already updated
    if jobs[job_id].get("status") != "awaiting_payment":
        logger.warning(f"Payment callback received for job {job_id} which is not awaiting payment (status: {jobs[job_id].get('status')}). Ignoring.")
        # Optional: Still stop monitoring here?
        if job_id in payment_instances:
             payment_instances[job_id].stop_status_monitoring()
             del payment_instances[job_id]
        return

    logger.info(f"Payment {payment_id} confirmed for job {job_id}, executing task...")

    # Update job status immediately
    jobs[job_id]["status"] = "running"
    jobs[job_id]["payment_status"] = "completed" # Payment is confirmed

    try:
        # Retrieve the original input topic string
        original_topic = jobs[job_id].get("input_data")
        if original_topic is None:
             logger.error(f"Input data (topic) not found for job {job_id} in callback.")
             raise ValueError("Input data (topic) not found for job.")

        # Reconstruct the input dictionary expected by the crew
        crew_inputs = {"topic": original_topic}

        # Execute the AI task
        result = await execute_crew_task(crew_inputs)
        logger.info(f"Crew task completed for job {job_id}")

        # Mark payment as completed on Masumi
        result_hash = str(result)[:64] # Truncate result for hash as per example
        await payment_instances[job_id].complete_payment(payment_id, result_hash)
        logger.info(f"Masumi payment marked as completed for job {job_id}")

        # Update final job status and result
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result

    except Exception as e:
        logger.error(f"Error during task execution or payment completion for job {job_id}: {e}", exc_info=True)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["message"] = f"Error after payment confirmation: {str(e)}"
        # Consider how to handle Masumi payment completion if task fails

    finally:
        # Stop monitoring payment status and clean up instance
        if job_id in payment_instances:
            payment_instances[job_id].stop_status_monitoring()
            del payment_instances[job_id]
            logger.debug(f"Stopped monitoring and cleaned up payment instance for job {job_id}")


# --- API Endpoints ---
@app.get("/availability", response_model=Availability, tags=["Status"])
async def get_availability():
    """Check basic service availability."""
    logger.info("Availability check requested.")
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key is not set.")
    if config is None:
         logger.warning("Masumi Payment configuration is missing or incomplete.")
         # You might want to reflect this in the status message
         # return Availability(status="degraded", message="Masumi Payment config missing.")
    return Availability(status="available", message="Agent is operational.")


@app.post("/start_job")
async def start_job(
    data: StartJobRequest,
    job_id: str = Query(default=None, description="Optional pre-generated job identifier")
):
    """
    Initiates a job and creates a Masumi payment request (fixed pricing)
    using FixedPayment which always sends RequestedFunds: null.
    """
    # 1) Config & env checks
    logger.info(f"Received request to start job with topic: {data.topic}")
    if config is None:
        raise HTTPException(503, "Masumi Payment Service not configured")
    if not PAYMENT_API_KEY:
        raise HTTPException(503, "Masumi Payment API Key not configured")
    if not AGENT_IDENTIFIER:
        raise HTTPException(503, "Masumi Agent Identifier not configured")

    # 2) Generate or accept job_id
    if not job_id:
        job_id = str(uuid.uuid4())
    logger.info(f"Processing job_id: {job_id}")

    # 3) Build display-only amounts list
    amt_str = os.getenv("PAYMENT_AMOUNT", "10000000")
    unit    = os.getenv("PAYMENT_UNIT",   "lovelace")
    display_amounts = [Amount(amount=amt_str, unit=unit)]

    # 4) Prepare purchaser identifier & input_data
    purchase_identifier = f"job_{job_id}"[:25]
    input_data_string   = json.dumps({"topic": data.topic}, sort_keys=True)
    logger.debug(f"input_data_string: {input_data_string}")

    # 5) Instantiate FixedPayment (empty amounts internally)
    try:
        payment = FixedPayment(
            agent_identifier=AGENT_IDENTIFIER,
            config=config,
            identifier_from_purchaser=purchase_identifier,
            input_data=input_data_string
        )
        logger.info(f"Initialized FixedPayment (input_hash={payment.input_hash})")
    except Exception as e:
        logger.error(f"Payment SDK init error for job {job_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Payment SDK init error: {e}")

    # 6) Create the payment request via our override
    try:
        logger.info(f"Calling create_payment_request() for job {job_id}")
        resp = await payment.create_payment_request()
        block = resp["data"]
        payment_id = block["blockchainIdentifier"]
    except httpx.HTTPStatusError as e:
        logger.error(f"Payment HTTP error for job {job_id}: {e.response.text}", exc_info=True)
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        logger.error(f"Error during create_payment_request for job {job_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Payment request failed: {e}")

    # 7) Record the payment ID for monitoring
    payment.payment_ids.add(payment_id)

    # 8) Store job info and start status monitoring
    jobs[job_id] = {
        "status":         "awaiting_payment",
        "payment_status": "pending",
        "payment_id":     payment_id,
        "input_query":    data.topic,
        "result":         None,
        "message":        None
    }
    async def payment_callback(cb_pid: str):
        await handle_payment_status(job_id, cb_pid)

    payment_instances[job_id] = payment
    await payment.start_status_monitoring(payment_callback)
    logger.info(f"Monitoring payment for job {job_id}, payment ID {payment_id}")

    # 9) Return the start_job response
    return {
        "job_id":                    job_id,
        "blockchainIdentifier":      payment_id,
        "submitResultTime":          block["submitResultTime"],
        "unlockTime":                block["unlockTime"],
        "externalDisputeUnlockTime": block["externalDisputeUnlockTime"],
        "agentIdentifier":           AGENT_IDENTIFIER,
        "sellerVkey":                SELLER_VKEY,
        "identifierFromPurchaser":   purchase_identifier,
        "amounts":                   [a.dict() for a in display_amounts],
        "input_hash":                payment.input_hash
    }


@app.get("/status/{job_id}", response_model=JobStatus, tags=["Crew Execution"])
async def get_job_status(job_id: str):
    """Check the status of a background job, including payment status."""
    logger.info(f"Status check requested for job ID: {job_id}")
    job = jobs.get(job_id)
    if not job:
        logger.warning(f"Job ID {job_id} not found.")
        raise HTTPException(status_code=404, detail="Job not found")

    # Return the current status, including payment_status updated by callback
    return JobStatus(
        job_id=job_id,
        status=job.get("status", "unknown"),
        payment_status=job.get("payment_status"), # Get stored payment status
        message=job.get("message")
    )

@app.get("/result/{job_id}", response_model=JobResult, tags=["Crew Execution"])
async def get_job_result(job_id: str):
    """Retrieve the result of a completed background job."""
    logger.info(f"Result requested for job ID: {job_id}")
    job = jobs.get(job_id)
    if not job:
        logger.warning(f"Job ID {job_id} not found.")
        raise HTTPException(status_code=404, detail="Job not found")

    # Add payment status check here as well for completeness
    current_payment_status = job.get("payment_status")
    current_job_status = job.get("status")

    if current_job_status != "completed":
        logger.warning(f"Job {job_id} is not completed. Current status: {current_job_status}, Payment status: {current_payment_status}")
        return JobResult(
            job_id=job_id,
            status=current_job_status,
            payment_status=current_payment_status,
            message=job.get("message", "Job is not yet completed."),
            result=None
       )

    logger.info(f"Returning result for completed job {job_id}.")
    return JobResult(
        job_id=job_id,
        status=job["status"],
        payment_status=job.get("payment_status"), # Include payment status
        message=job.get("message"),
        result=job.get("result")
    )


@app.get("/", tags=["Status"])
async def read_root():
    """Root endpoint for basic check."""
    logger.info("Root endpoint accessed.")
    return {"message": "Welcome to the Cardano Governance Crew Agent API (Masumi Integrated)!"}


@app.get("/input_schema", tags=["Crew Execution"])
async def input_schema():
    """
    Returns the expected input schema for the /start_job endpoint.
    Fulfills MIP-003 /input_schema endpoint.
    """
    # Update to reflect your actual input ('topic')
    schema_example = {
        "input_data": [
            {
                "id": "topic", # Matches your StartJobRequest
                "type": "string",
                "name": "Governance Topic", # Descriptive name
                "data": {
                    "description": "The topic for Cardano governance analysis",
                    "placeholder": "Enter the governance topic here"
                }
            }
        ]
    }
    return schema_example

