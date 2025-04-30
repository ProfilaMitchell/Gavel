import httpx
import os
import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from masumi_crewai.config import Config
from masumi_crewai.payment import Payment, Amount
import hashlib
import json # Ensure json is imported
import redis # Ensure redis is imported

from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
# Note: httpx is imported twice, keep only one if preferred
# import httpx

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")


# --- Load Environment Variables ---
# Load .env file from the current directory (src)
load_dotenv()

# --- Masumi Payment Configuration (from .env) ---
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:3001/api/v1")
PAYMENT_API_KEY = os.getenv("PAYMENT_API_KEY")
AGENT_IDENTIFIER = os.getenv("AGENT_IDENTIFIER")
PAYMENT_AMOUNT = int(os.getenv("PAYMENT_AMOUNT", "10000000"))
PAYMENT_UNIT = os.getenv("PAYMENT_UNIT", "lovelace")
SELLER_VKEY = os.getenv("SELLER_VKEY")
# Add OPENAI_API_KEY check here as it was used in /availability later
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Cardano Governance Crew Agent (Masumi Integrated)",
    description="Agent using @CrewBase structure.",
    version="1.3.0" # Incremented version
)

# --- Mount static files directory ---
# Assumes 'static' directory is in the same place as main.py
#app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info(f"Mounted static directory: {STATIC_DIR}")
else:
    logger.error(f"Static directory not found at: {STATIC_DIR}. Static files will not be served.")

# --- Setup Templates ---
# Assumes 'templates' directory is in the same place as main.py
#templates = Jinja2Templates(directory="templates")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
logger.info(f"Configured template directory: {TEMPLATE_DIR}")

# --- REMOVE In-Memory Job Store ---
# jobs = {} # Removed
# Keep payment_instances in memory for now
payment_instances: Dict[str, Payment] = {}

# --- Initialize Masumi Payment Config ---
config = None
if not all([PAYMENT_SERVICE_URL, PAYMENT_API_KEY]):
    logger.error("MASUMI_PAYMENT_SERVICE_URL or MASUMI_PAYMENT_API_KEY missing from environment. Masumi features disabled.")
else:
    try:
        config = Config(
            payment_service_url=PAYMENT_SERVICE_URL,
            payment_api_key=PAYMENT_API_KEY
        )
        logger.info("Masumi Payment Config Initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Masumi Config: {e}")
        config = None # Ensure config is None on failure

# --- Pydantic Models for API ---
class StartJobRequest(BaseModel):
    proposal_query: str = Field(..., example="188") # Updated example

class JobStatus(BaseModel):
    job_id: str
    status: str
    payment_status: Optional[str] = None
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
        # Return error string instead of raising ValueError here if called externally
        return "Error: Crew class not available."
    try:
        crew_instance = CardanoGovernanceCrew()
        result = crew_instance.crew().kickoff(inputs=inputs)
        logger.info("Crew task kickoff completed.")
        # Ensure result is serializable or handle appropriately
        # For now, return string representation
        return str(result)
    except Exception as e:
        logger.error(f"Error during Crew task execution: {e}", exc_info=True)
        return f"Error executing crew task: {e}"


# --- Payment Callback Handler (Modified for Redis) ---
async def handle_payment_status(job_id: str, payment_id: str, redis_conn_callback: redis.Redis) -> None:
    """ Executes CrewAI task after payment confirmation, using Redis """
    logger.info(f"Payment {payment_id} completed for job {job_id}, executing task...")

    if not redis_conn_callback:
        logger.error(f"Redis connection not available in handle_payment_status for job {job_id}")
        return

    try:
        # Update job status to running in Redis
        update_running = {"status": "running", "payment_status": "paid"}
        redis_conn_callback.hset(name=job_id, mapping=update_running)

        # Get the original input data from Redis
        input_query = redis_conn_callback.hget(job_id, "input_data")
        if not input_query:
            logger.error(f"Could not retrieve input_data for job {job_id} from Redis.")
            update_failed_input = {"status": "failed", "message": "Failed to retrieve input data"}
            redis_conn_callback.hset(name=job_id, mapping=update_failed_input)
            return

        crew_inputs = {"proposal_query": input_query}

        if CardanoGovernanceCrew is None:
             logger.error("CardanoGovernanceCrew not available for task execution.")
             raise ImportError("CardanoGovernanceCrew class not loaded.")

        crew_instance = CardanoGovernanceCrew()
        # Directly execute the crew task (can block if long-running - consider background task runner for production)
        result = crew_instance.crew().kickoff(inputs=crew_inputs)
        logger.info(f"Crew task completed for job {job_id}")

        # Serialize the result
        try:
             result_str = json.dumps(result)
        except TypeError as e:
             logger.warning(f"Result for job {job_id} is not JSON serializable: {e}. Storing as string.")
             result_str = str(result)

        # Mark payment as completed on Masumi
        result_hash = result_str[:64] if len(result_str) >= 64 else result_str
        if job_id in payment_instances:
            await payment_instances[job_id].complete_payment(payment_id, result_hash)
            logger.info(f"Payment marked as completed for job {job_id}")
        else:
            logger.warning(f"Payment instance for job {job_id} not found, cannot mark complete.")

        # Update final job status and result in Redis
        update_completed = {
            "status": "completed",
            "payment_status": "completed",
            "result": result_str,
            "message": ""
        }
        redis_conn_callback.hset(name=job_id, mapping=update_completed)

    except Exception as e:
        logger.error(f"Error processing job {job_id} after payment: {str(e)}", exc_info=True)
        error_message = f"Error processing task after payment: {str(e)}"
        update_failed = {"status": "failed", "message": error_message}
        # Ensure connection exists before trying to update status on error
        if redis_conn_callback:
             redis_conn_callback.hset(name=job_id, mapping=update_failed)

    finally:
        # Stop monitoring payment status
        if job_id in payment_instances:
            try:
                 payment_instances[job_id].stop_status_monitoring()
            except Exception as stop_err:
                 logger.error(f"Error stopping monitoring for job {job_id}: {stop_err}", exc_info=True)
            finally:
                 del payment_instances[job_id]


# --- API Endpoints ---

# Helper function to get Redis connection (moved inside endpoints for simplicity now)
# def get_redis_connection(request: Request) -> redis.Redis | None: ...

# --- Root UI Endpoint ---
@app.get("/", response_class=HTMLResponse, tags=["UI"])
async def read_index(request: Request):
    """Serves the main HTML user interface."""
    logger.info("Root UI endpoint accessed.")
    return templates.TemplateResponse("index.html", {"request": request})

# --- Availability Endpoint ---
@app.get("/availability", response_model=Availability, tags=["Status"])
async def get_availability(request: Request): # Add request
    """Check basic service availability."""
    logger.info("Availability check requested.")
    # Check dependency statuses
    messages = []
    status = "available"
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key is not set.")
        messages.append("OpenAI API key missing.")
        status = "degraded"
    if config is None:
         logger.warning("Masumi Payment configuration is missing or incomplete.")
         messages.append("Masumi config missing.")
         status = "degraded"
    # Check Redis connection
    redis_conn_avail = getattr(request.app.state, 'redis_conn', None)
    if not redis_conn_avail:
         logger.warning("Redis connection not available.")
         messages.append("Redis connection failed.")
         status = "degraded"
    else:
         try:
              redis_conn_avail.ping()
         except redis.exceptions.ConnectionError:
              logger.warning("Redis ping failed during availability check.")
              messages.append("Redis connection failed.")
              status = "degraded"

    final_message = "Agent is operational." if status == "available" else " | ".join(messages)
    return Availability(status=status, message=final_message)

# --- Start Job Endpoint (Modified for Redis) ---
@app.post("/start_job", status_code=202) # Use 202 Accepted for async job start
async def start_job(data: StartJobRequest, request: Request):
    """ Initiates a job and creates a payment request, storing job in Redis """
    redis_conn = getattr(request.app.state, 'redis_conn', None)
    if not redis_conn:
         raise HTTPException(status_code=503, detail="Database connection not available")

    if not config: # Check if Masumi config is available
        raise HTTPException(status_code=503, detail="Masumi Payment Service not configured")

    try:
        job_id = str(uuid.uuid4())
        logger.info(f"Creating new job {job_id} with input query: {data.proposal_query}")

        agent_identifier = os.getenv("AGENT_IDENTIFIER")
        if not agent_identifier:
            logger.error("AGENT_IDENTIFIER not found in environment.")
            raise HTTPException(status_code=500, detail="Agent identifier not configured")

        identifier_from_purchaser = f"job_{job_id[:20]}"

        crew_input_dict = {"proposal_query": data.proposal_query}
        input_data_string = json.dumps(crew_input_dict, sort_keys=True)
        input_hash = hashlib.sha256(input_data_string.encode('utf-8')).hexdigest()
        logger.info(f"Generated input hash: {input_hash}")

        # --- Timestamps --- (Keep existing logic)
        submit_duration = timedelta(days=1)
        unlock_duration = timedelta(days=2)
        dispute_duration = timedelta(days=3)
        now_utc = datetime.now(timezone.utc)
        submit_time_dt = now_utc + submit_duration
        unlock_time_dt = now_utc + unlock_duration
        dispute_time_dt = now_utc + dispute_duration
        if unlock_time_dt <= submit_time_dt + timedelta(hours=1):
            unlock_time_dt = submit_time_dt + timedelta(hours=1)
        min_dispute_diff = timedelta(minutes=16)
        if dispute_time_dt <= unlock_time_dt + min_dispute_diff:
             dispute_time_dt = unlock_time_dt + min_dispute_diff
        submit_time_iso = submit_time_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        unlock_time_iso = unlock_time_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        dispute_time_iso = dispute_time_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        logger.info(f"Calculated ISO timestamps: submit={submit_time_iso}, unlock={unlock_time_iso}, dispute={dispute_time_iso}")

        # --- Masumi API Call --- (Keep existing logic)
        payment_service_url = f"{PAYMENT_SERVICE_URL.rstrip('/')}/payment"
        payload = {
            "agentIdentifier": agent_identifier, "network": "Preprod",
            "paymentType": "Web3CardanoV1", "identifierFromPurchaser": identifier_from_purchaser,
            "inputHash": input_hash, "submitResultTime": submit_time_iso,
            "unlockTime": unlock_time_iso, "externalDisputeUnlockTime": dispute_time_iso
        }
        headers = {"Content-Type": "application/json", "token": PAYMENT_API_KEY}
        payment_id = None
        payment_data_response = None # Store response data for return
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(payment_service_url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Payment service error ({response.status_code}): {response.text}")
                raise HTTPException(status_code=response.status_code, detail=f"Payment service error: {response.text}")
            payment_data = response.json()
            if "data" not in payment_data or "blockchainIdentifier" not in payment_data["data"]:
                logger.error(f"Invalid payment service response: {payment_data}")
                raise HTTPException(status_code=500, detail="Invalid payment service response")
            payment_id = payment_data["data"]["blockchainIdentifier"]
            payment_data_response = payment_data["data"] # Save for return

        # --- Store Initial Job Data in Redis ---
        initial_job_data = {
            "status": "awaiting_payment", "payment_status": "pending",
            "payment_id": payment_id, "input_data": data.proposal_query,
            "input_hash": input_hash, "result": "", "message": ""
        }
        redis_conn.hset(name=job_id, mapping=initial_job_data)
        redis_conn.expire(name=job_id, time=timedelta(days=7)) # Set expiry
        logger.info(f"Stored initial job data for {job_id} in Redis.")

        # --- Setup Masumi Monitoring ---
        amounts = [Amount(amount=str(PAYMENT_AMOUNT), unit=PAYMENT_UNIT)] # Ensure amount is string if needed
        monitoring_payment = Payment(
            agent_identifier=agent_identifier, amounts=amounts,
            config=config, identifier_from_purchaser=identifier_from_purchaser
        )
        monitoring_payment.payment_ids.add(payment_id)
        payment_instances[job_id] = monitoring_payment

        # --- Define and Start Callback ---
        async def payment_callback_wrapper(payment_id_cb: str):
            # Need access to redis_conn established in app state
            # Since this runs async, getting request state is hard.
            # Option 1: Pass redis_conn (done below)
            # Option 2: Re-establish connection inside callback (less ideal)
            # Option 3: Use global (not ideal in async framework)
            redis_conn_for_callback = getattr(app.state, 'redis_conn', None) # Try accessing app state directly
            await handle_payment_status(job_id, payment_id_cb, redis_conn_callback=redis_conn_for_callback)

        await monitoring_payment.start_status_monitoring(payment_callback_wrapper)

        seller_vkey = os.getenv("SELLER_VKEY")
        if not seller_vkey:
            # Don't raise 500, maybe return warning or default key if applicable?
            logger.warning("SELLER_VKEY not found in environment")
            # raise HTTPException(status_code=500, detail="Seller vkey not configured")

        # --- Return Response ---
        return {
            "status": "success", "job_id": job_id,
            "blockchainIdentifier": payment_id,
            "submitResultTime": payment_data_response.get("submitResultTime"),
            "unlockTime": payment_data_response.get("unlockTime"),
            "externalDisputeUnlockTime": payment_data_response.get("externalDisputeUnlockTime"),
            "agentIdentifier": agent_identifier, "sellerVkey": seller_vkey,
            "identifierFromPurchaser": identifier_from_purchaser,
            "amounts": [{"amount": str(amounts[0].amount), "unit": amounts[0].unit}], # Return as strings
            "input_hash": input_hash
        }

    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Error creating job {job_id if 'job_id' in locals() else 'unknown'}: {str(e)}", exc_info=True)
        # Try to clean up Redis entry if job creation failed mid-way? Difficult.
        raise HTTPException(status_code=500, detail=f"Internal server error creating job: {str(e)}")


# --- Status Endpoint (Modified for Redis) ---
@app.get("/status/{job_id}", response_model=JobStatus, tags=["Crew Execution"])
async def get_job_status(job_id: str, request: Request):
    """Check the status of a background job from Redis."""
    redis_conn = getattr(request.app.state, 'redis_conn', None)
    if not redis_conn:
         raise HTTPException(status_code=503, detail="Database connection not available")

    logger.info(f"Status check requested for job ID: {job_id}")

    if not redis_conn.exists(job_id):
        logger.warning(f"Job ID {job_id} not found in Redis.")
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = redis_conn.hgetall(job_id)

    return JobStatus(
        job_id=job_id,
        status=job_data.get("status", "unknown"),
        payment_status=job_data.get("payment_status"),
        message=job_data.get("message")
    )

# --- Result Endpoint (Modified for Redis) ---
@app.get("/result/{job_id}", response_model=JobResult, tags=["Crew Execution"])
async def get_job_result(job_id: str, request: Request):
    """Retrieve the result of a completed background job from Redis."""
    redis_conn = getattr(request.app.state, 'redis_conn', None)
    if not redis_conn:
         raise HTTPException(status_code=503, detail="Database connection not available")

    logger.info(f"Result requested for job ID: {job_id}")

    if not redis_conn.exists(job_id):
        logger.warning(f"Job ID {job_id} not found in Redis.")
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = redis_conn.hgetall(job_id)
    current_job_status = job_data.get("status", "unknown")

    if current_job_status != "completed":
        logger.warning(f"Job {job_id} is not completed. Current status: {current_job_status}")
        return JobResult(
            job_id=job_id,
            status=current_job_status,
            payment_status=job_data.get("payment_status"),
            message=job_data.get("message", "Job is not yet completed."),
            result=None
       )

    logger.info(f"Returning result for completed job {job_id}.")

    raw_result = job_data.get("result")
    final_result = None
    if raw_result:
        try:
            final_result = json.loads(raw_result)
        except json.JSONDecodeError:
            logger.warning(f"Could not decode result for job {job_id} from JSON, returning raw string.")
            final_result = raw_result

    return JobResult(
        job_id=job_id,
        status=current_job_status, # Use fetched status
        payment_status=job_data.get("payment_status"),
        message=job_data.get("message"),
        result=final_result
    )

# --- Input Schema Endpoint ---
@app.get("/input_schema", tags=["Crew Execution"])
async def input_schema():
    """
    Returns the expected input schema for the /start_job endpoint.
    Fulfills MIP-003 /input_schema endpoint.
    """
    schema_example = {
        "input_data": [
            {
                "id": "proposal_query", # Changed ID
                "type": "string",
                "name": "Proposal Query/ID", # Changed Name
                "data": {
                    "description": "The specific Cardano governance proposal ID or a search query (e.g., 'latest', '11097', 'Treasury System').", # Changed Description
                    "placeholder": "Enter proposal ID or query" # Changed Placeholder
                }
            }
        ]
    }
    return schema_example

# --- Event Handlers (Keep corrected versions) ---
@app.on_event("startup")
async def startup_event():
    logger.warning("!!! Running startup_event function...")
    logger.info("Application startup: Initializing Redis connection...")
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    REDIS_DB = int(os.getenv("REDIS_DB", 0))

    app.state.redis_pool = None
    app.state.redis_conn = None
    temp_pool = None
    temp_conn = None

    try:
        temp_pool = redis.ConnectionPool(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
            db=REDIS_DB, decode_responses=True
        )
        temp_conn = redis.Redis(connection_pool=temp_pool)
        temp_conn.ping()
        logger.info(f"Successfully connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        app.state.redis_pool = temp_pool
        app.state.redis_conn = temp_conn
        logger.warning("!!! Redis connection successful and assigned to app.state.")

    except redis.exceptions.ConnectionError as e:
        logger.error(f"Failed to connect to Redis during startup: {e}", exc_info=True)
        logger.warning("!!! Redis connection FAILED (ConnectionError).")
        app.state.redis_pool = None
        app.state.redis_conn = None
        if temp_pool: temp_pool.disconnect()

    except Exception as e:
        logger.error(f"An unexpected error occurred during Redis setup: {e}", exc_info=True)
        logger.warning(f"!!! Redis connection FAILED (Other Error: {type(e).__name__}).")
        app.state.redis_pool = None
        app.state.redis_conn = None
        if temp_pool: temp_pool.disconnect()

@app.on_event("shutdown")
async def shutdown_event():
     redis_pool = getattr(app.state, 'redis_pool', None)
     if redis_pool:
         try:
             redis_pool.disconnect()
             logging.info("Redis connection pool disconnected.")
         except Exception as e:
              logging.error(f"Error disconnecting Redis pool: {e}", exc_info=True)

# --- End of File ---