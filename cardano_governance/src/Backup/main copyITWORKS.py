import httpx 
import os
import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from masumi_crewai.config import Config
from masumi_crewai.payment import Payment, Amount
import hashlib
import json

from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Request
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
    """ Executes CrewAI task after payment confirmation """
    logger.info(f"Payment {payment_id} completed for job {job_id}, executing task...")
    
    # Update job status to running
    jobs[job_id]["status"] = "running"
    
    try:
        # Get the original input data
        input_data = jobs[job_id]["input_data"]
        
        # Prepare input for your crew
        crew_inputs = {"topic": input_data}  # Adjust based on your crew's expected input format
        
        # Execute the AI task
        crew_instance = CardanoGovernanceCrew()
        result = crew_instance.crew().kickoff(inputs=crew_inputs)
        logger.info(f"Crew task completed for job {job_id}")

        # Convert result to string if it's not already
        result_str = str(result)
        
        # Mark payment as completed on Masumi
        # Use a shorter string for the result hash
        result_hash = result_str[:64] if len(result_str) >= 64 else result_str
        await payment_instances[job_id].complete_payment(payment_id, result_hash)
        logger.info(f"Payment marked as completed for job {job_id}")

        # Update job status
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["payment_status"] = "completed"
        jobs[job_id]["result"] = result
    
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}", exc_info=True)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["message"] = f"Error processing task: {str(e)}"
    
    finally:
        # Stop monitoring payment status
        if job_id in payment_instances:
            payment_instances[job_id].stop_status_monitoring()
            del payment_instances[job_id]


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
async def start_job(data: StartJobRequest):
    """ Initiates a job and creates a payment request """
    try:
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        logger.info(f"Creating new job {job_id} with input: {data.topic}")
        
        # Get agent identifier from environment
        agent_identifier = os.getenv("AGENT_IDENTIFIER")
        if not agent_identifier:
            logger.error("AGENT_IDENTIFIER not found in environment.")
            raise HTTPException(status_code=500, detail="Agent identifier not configured")
        
        # Generate identifier for this purchase 
        identifier_from_purchaser = f"job_{job_id[:20]}"
        
        # Generate input hash
        crew_input_dict = {"topic": data.topic}
        input_data_string = json.dumps(crew_input_dict, sort_keys=True)
        input_hash = hashlib.sha256(input_data_string.encode('utf-8')).hexdigest()
        logger.info(f"Generated input hash: {input_hash}")

        # --- Calculate Future Timestamps ---
        # Define desired durations (adjust as needed)
        submit_duration = timedelta(days=1) # Agent has 1 day to submit result
        unlock_duration = timedelta(days=2) # Funds unlock 2 days from now
        dispute_duration = timedelta(days=3) # Dispute period ends 3 days from now

        now_utc = datetime.now(timezone.utc)

        # Calculate initial absolute timestamps
        submit_time_dt = now_utc + submit_duration
        unlock_time_dt = now_utc + unlock_duration
        dispute_time_dt = now_utc + dispute_duration # <<< *** ADDED THIS LINE ***

        # --- Adjust Timestamps to ensure correct sequence and minimum gaps ---
        # Ensure unlock time is sufficiently after submit time (e.g., at least 1 hour)
        if unlock_time_dt <= submit_time_dt + timedelta(hours=1):
            logger.warning("Adjusting unlockTime to be 1 hour after submitResultTime.")
            unlock_time_dt = submit_time_dt + timedelta(hours=1)

        # Ensure external dispute time is sufficiently after unlock time (at least 15 mins)
        min_dispute_diff = timedelta(minutes=16) # Use 16 mins for safety buffer
        if dispute_time_dt <= unlock_time_dt + min_dispute_diff:
             logger.warning("Adjusting externalDisputeUnlockTime to be >15 mins after unlockTime.")
             dispute_time_dt = unlock_time_dt + min_dispute_diff

        # Format as ISO 8601 strings ("YYYY-MM-DDTHH:MM:SS.sssZ")
        submit_time_iso = submit_time_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        unlock_time_iso = unlock_time_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        dispute_time_iso = dispute_time_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z' # Now this uses the correctly calculated dt

        logger.info(f"Calculated ISO timestamps for POST /payment request: "
                    f"submit={submit_time_iso}, unlock={unlock_time_iso}, dispute={dispute_time_iso}")

        
        # Manual API call to Masumi Payment Service
        payment_service_url = f"{PAYMENT_SERVICE_URL.rstrip('/')}/payment"
        
        # Create payload
        payload = {
            "agentIdentifier": agent_identifier,
            "network": "Preprod",
            "paymentType": "Web3CardanoV1",
            "identifierFromPurchaser": identifier_from_purchaser,
            "inputHash": input_hash,
            # --- Add Timestamps ---
            "submitResultTime": submit_time_iso,
            "unlockTime": unlock_time_iso,
            "externalDisputeUnlockTime": dispute_time_iso
            # For fixed pricing, leave out requestedFunds
        }
        logger.info(f"Payload for POST /payment (with timestamps): {payload}")
        
        headers = {
            "Content-Type": "application/json",
            "token": PAYMENT_API_KEY
        }
        
        # Make the API call
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                payment_service_url,
                headers=headers,
                json=payload
            )
            
            if response.status_code != 200:
                logger.error(f"Payment service error: {response.text}")
                raise HTTPException(status_code=response.status_code, 
                                   detail=f"Payment service error: {response.text}")
                
            payment_data = response.json()
            if "data" not in payment_data or "blockchainIdentifier" not in payment_data["data"]:
                logger.error(f"Invalid payment service response: {payment_data}")
                raise HTTPException(status_code=500, 
                                   detail="Invalid payment service response")
                
            payment_id = payment_data["data"]["blockchainIdentifier"]
            
        # Create Payment instance for monitoring
        # Define payment amounts (for monitoring only)
        amounts = [Amount(
            amount=os.getenv("PAYMENT_AMOUNT", "10000000"),
            unit=os.getenv("PAYMENT_UNIT", "lovelace")
        )]
        
        # Create monitoring payment object
        monitoring_payment = Payment(
            agent_identifier=agent_identifier,
            amounts=amounts,
            config=config,
            identifier_from_purchaser=identifier_from_purchaser
        )
        monitoring_payment.payment_ids.add(payment_id)
        
        # Store job info 
        jobs[job_id] = {
            "status": "awaiting_payment",
            "payment_status": "pending",
            "payment_id": payment_id,
            "input_data": data.topic,
            "input_hash": input_hash,
            "result": None
        }

        # Set up payment callback
        async def payment_callback(payment_id_cb: str):
            await handle_payment_status(job_id, payment_id_cb)

        # Start monitoring
        payment_instances[job_id] = monitoring_payment
        await monitoring_payment.start_status_monitoring(payment_callback)
        
        # Get seller_vkey from environment
        seller_vkey = os.getenv("SELLER_VKEY")
        if not seller_vkey:
            logger.warning("SELLER_VKEY not found in environment")
            raise HTTPException(status_code=500, detail="Seller vkey not configured")

        # Return the response in the required format
        return {
            "status": "success",
            "job_id": job_id,
            "blockchainIdentifier": payment_id,
            "submitResultTime": payment_data["data"].get("submitResultTime"),
            "unlockTime": payment_data["data"].get("unlockTime"),
            "externalDisputeUnlockTime": payment_data["data"].get("externalDisputeUnlockTime"),
            "agentIdentifier": agent_identifier,
            "sellerVkey": seller_vkey,
            "identifierFromPurchaser": identifier_from_purchaser,
            "amounts": [{"amount": amounts[0].amount, "unit": amounts[0].unit}],
            "input_hash": input_hash
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating job: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating job: {str(e)}")


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

