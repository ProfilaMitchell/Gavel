import os
import uuid
import logging
from typing import Dict, Any, Optional

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

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Cardano Governance Crew Agent (Refactored)",
    description="Agent using @CrewBase structure.",
    version="1.1.0" # Incremented version
)

# --- In-Memory Job Store ---
# IMPORTANT: Replace with a persistent store (Redis, DB) for production
jobs: Dict[str, Dict[str, Any]] = {}

# --- Pydantic Models for API ---
class JobInput(BaseModel):
    # Define inputs expected by the crew's kickoff method
    # These should match the variables used in your task descriptions (e.g., {topic})
    topic: str = Field(..., example="Analyze latest governance proposals")
    # Add other inputs if your tasks use them, e.g.:
    # max_proposals: Optional[int] = Field(default=1, example=1)

class JobStatus(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None

class JobResult(JobStatus):
    result: Optional[Any] = None

class Availability(BaseModel):
    status: str = "available"
    message: Optional[str] = None


# --- Masumi Payment Configuration (from .env) ---
MASUMI_PAYMENT_SERVICE_URL = os.getenv("MASUMI_PAYMENT_SERVICE_URL", "http://localhost:3001/api/v1")
MASUMI_PAYMENT_API_KEY = os.getenv("MASUMI_PAYMENT_API_KEY")
AGENT_IDENTIFIER = os.getenv("AGENT_IDENTIFIER")
PAYMENT_AMOUNT = int(os.getenv("PAYMENT_AMOUNT", "1000000"))
PAYMENT_UNIT = os.getenv("PAYMENT_UNIT", "lovelace")
SELLER_VKEY = os.getenv("SELLER_VKEY")

# --- Helper Function for Masumi Payment Verification (Placeholder) ---
async def verify_masumi_payment(payment_token: Optional[str]) -> bool:
    """Placeholder for Masumi payment verification."""
    if not all([MASUMI_PAYMENT_SERVICE_URL, MASUMI_PAYMENT_API_KEY, AGENT_IDENTIFIER, SELLER_VKEY]):
         logger.warning("Masumi environment variables not fully configured. Skipping payment verification.")
         return True # Allow proceeding for now if not configured
    if not payment_token:
        logger.warning("No Masumi payment token provided in the request.")
        # Decide if free access is allowed or token is mandatory
        return True # Allow proceeding for now
    logger.info(f"Placeholder: Assuming payment verified for token: {payment_token}")
    # Replace with actual call to Masumi /verify endpoint using httpx
    return True


# --- Background Task Function ---
def run_crew_background(job_id: str, inputs: Dict[str, Any]):
    """
    Runs the CrewAI agent tasks in the background using the @CrewBase structure.
    Updates the job status in the in-memory store.
    """
    logger.info(f"Starting background job {job_id} with inputs: {inputs}")
    jobs[job_id] = {"status": "running", "message": "Crew execution started."}

    try:
        if CardanoGovernanceCrew is None:
             # This check ensures the import worked before trying to instantiate
             raise ImportError("CardanoGovernanceCrew class was not imported successfully during startup.")

        # Instantiate the @CrewBase class
        # The @crew decorator handles the Crew object creation internally
        crew_instance = CardanoGovernanceCrew()

        # Kick off the crew using the @crew method and kickoff()
        # Pass the inputs dictionary directly to kickoff
        # The crew defined by the @crew decorator will be executed
        logger.info(f"Instantiated crew. Kicking off job {job_id}...")
        result = crew_instance.crew().kickoff(inputs=inputs)
        logger.info(f"Crew kickoff completed for job {job_id}.")

        # Store the result and update status
        jobs[job_id] = {"status": "completed", "result": result}
        logger.info(f"Background job {job_id} completed successfully.")

    except ImportError as ie:
        logger.error(f"Import error during background job {job_id}: {ie}")
        jobs[job_id] = {"status": "failed", "message": f"Import Error: {ie}"}
    except ValueError as ve: # Catches config errors like missing API keys from _initialize_llm
        logger.error(f"Configuration error during background job {job_id}: {ve}")
        jobs[job_id] = {"status": "failed", "message": f"Configuration Error: {ve}"}
    except Exception as e: # Catch any other unexpected errors during crew execution
        logger.error(f"Error during background job {job_id}: {e}", exc_info=True) # Log traceback
        jobs[job_id] = {"status": "failed", "message": f"An unexpected error occurred: {str(e)}"}


# --- API Endpoints ---
@app.get("/availability", response_model=Availability, tags=["Status"])
async def get_availability():
    """Check basic service availability."""
    logger.info("Availability check requested.")
    # Add more checks if needed (e.g., check OPENAI_API_KEY)
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OpenAI API key is not set in environment.")
        # Still report available, but maybe degraded? Or just log warning.
        # return Availability(status="degraded", message="OpenAI API key missing.")
    return Availability(status="available", message="Agent is operational.")

@app.post("/start_job", response_model=JobStatus, status_code=202, tags=["Crew Execution"])
async def start_job(
    job_input: JobInput,
    background_tasks: BackgroundTasks,
    request: Request # Keep request for potential future use (e.g., headers)
):
    """Starts a new background job to run the crew."""
    logger.info(f"Received request to start job with input: {job_input.dict()}")
    # --- Payment Verification Placeholder ---
    # payment_token = request.headers.get("X-Masumi-Payment-Token")
    # payment_verified = await verify_masumi_payment(payment_token)
    # if not payment_verified:
    #     logger.warning("Payment verification failed. Rejecting job request.")
    #     raise HTTPException(status_code=402, detail="Payment verification failed.")
    # logger.info("Payment verification successful (placeholder).")
    # --- End Placeholder ---

    job_id = str(uuid.uuid4())
    # Pass the validated input directly to the background task
    crew_inputs = job_input.dict()
    background_tasks.add_task(run_crew_background, job_id, crew_inputs)
    logger.info(f"Job {job_id} accepted and started in background.")
    return JobStatus(job_id=job_id, status="accepted", message="Job accepted and running in background.")

@app.get("/status/{job_id}", response_model=JobStatus, tags=["Crew Execution"])
async def get_job_status(job_id: str):
    """Check the status of a background job."""
    logger.info(f"Status check requested for job ID: {job_id}")
    job = jobs.get(job_id)
    if not job:
        logger.warning(f"Job ID {job_id} not found.")
        raise HTTPException(status_code=404, detail="Job not found")
    # Return the current status and any message
    return JobStatus(job_id=job_id, status=job.get("status", "unknown"), message=job.get("message"))

@app.get("/result/{job_id}", response_model=JobResult, tags=["Crew Execution"])
async def get_job_result(job_id: str):
    """Retrieve the result of a completed background job."""
    logger.info(f"Result requested for job ID: {job_id}")
    job = jobs.get(job_id)
    if not job:
        logger.warning(f"Job ID {job_id} not found.")
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "completed":
        logger.warning(f"Job {job_id} is not completed. Current status: {job.get('status')}")
        # Return current status instead of raising 400, more informative
        return JobResult(
            job_id=job_id,
            status=job.get("status"),
            message=job.get("message", "Job is not yet completed."),
            result=None # No result available yet
       )
        # raise HTTPException(status_code=400, detail=f"Job is not completed. Status: {job.get('status')}")

    logger.info(f"Returning result for completed job {job_id}.")
    return JobResult(
        job_id=job_id,
        status=job["status"],
        message=job.get("message"),
        result=job.get("result") # Return the actual result from the crew
    )

@app.get("/", tags=["Status"])
async def read_root():
    """Root endpoint for basic check."""
    logger.info("Root endpoint accessed.")
    return {"message": "Welcome to the Cardano Governance Crew Agent API!"}

# --- Running the App (for local development) ---
if __name__ == "__main__":
    # This block is mainly for informational purposes when running the file directly.
    # The recommended way to run for development is using the uvicorn command.
    print("-----------------------------------------------------------")
    print("To run the server for development, use the command:")
    print("uvicorn main:app --reload --host 127.0.0.1 --port 8000")
    print("(Run this command from the 'src' directory where this main.py is located)")
    print("-----------------------------------------------------------")

