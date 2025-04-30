from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import os
from dotenv import load_dotenv
import time
import requests
import json
from cardano_governance import analyze_text_sentiment, data_store
from cardano_governance.crew import CardanoGovernance

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="Cardano Governance Sentiment API",
    description="API for analyzing sentiment in Cardano governance proposals",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API key security
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Environment variables
MASUMI_API_KEY = os.getenv("MASUMI_API_KEY")
MASUMI_PAYMENT_URL = os.getenv("MASUMI_PAYMENT_URL", "http://localhost:3000/api/payments")
MASUMI_REGISTRY_URL = os.getenv("MASUMI_REGISTRY_URL", "http://localhost:3001/api/agents")
AGENT_ID = os.getenv("AGENT_ID")

# Rate limiting
rate_limit = {}

# Masumi integration
def verify_payment(request_id: str, amount: int):
    """Verify payment with Masumi Payment Service"""
    try:
        response = requests.post(
            f"{MASUMI_PAYMENT_URL}/verify",
            headers={"Authorization": f"Bearer {MASUMI_API_KEY}"},
            json={"requestId": request_id, "amount": amount}
        )
        return response.json()
    except Exception as e:
        print(f"Error verifying payment: {str(e)}")
        return {"status": "error", "message": str(e)}

def create_payment_request(amount: int, description: str):
    """Create payment request with Masumi Payment Service"""
    try:
        response = requests.post(
            f"{MASUMI_PAYMENT_URL}/create",
            headers={"Authorization": f"Bearer {MASUMI_API_KEY}"},
            json={"amount": amount, "description": description}
        )
        return response.json()
    except Exception as e:
        print(f"Error creating payment request: {str(e)}")
        return {"status": "error", "message": str(e)}

# API key validation
async def get_api_key(api_key_header: str = Depends(api_key_header)):
    if api_key_header:
        # In production, validate against a database of API keys
        valid_api_keys = {"test-api-key": {"tier": "free", "rate_limit": 10}}
        if api_key_header in valid_api_keys:
            return {"key": api_key_header, **valid_api_keys[api_key_header]}
    raise HTTPException(status_code=403, detail="Invalid or missing API key")

# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if "/api/" in request.url.path:
        # Get API key from header
        api_key = request.headers.get(API_KEY_NAME)
        
        # Check rate limit
        if api_key in rate_limit:
            # Get rate limit info
            limit_info = rate_limit[api_key]
            current_time = time.time()
            
            # Reset rate limit if window has passed
            if current_time - limit_info["window_start"] > 60:
                rate_limit[api_key] = {
                    "count": 1,
                    "window_start": current_time
                }
            else:
                # Check if rate limit exceeded
                if limit_info["count"] >= 10:  # Default rate limit
                    return JSONResponse(
                        status_code=429,
                        content={"status": "error", "message": "Rate limit exceeded"}
                    )
                # Increment count
                rate_limit[api_key]["count"] += 1
        else:
            # Initialize rate limit for this API key
            rate_limit[api_key] = {
                "count": 1,
                "window_start": time.time()
            }
    
    # Continue processing request
    response = await call_next(request)
    return response

# Models
class SentimentRequest(BaseModel):
    text: str

class ProposalSentimentRequest(BaseModel):
    proposal_id: str
    sentiment: float  # -1.0 to 1.0 scale

class PaymentVerificationRequest(BaseModel):
    request_id: str
    amount: int

# Routes
@app.get("/")
async def root():
    return {"message": "Cardano Governance Sentiment API", "status": "active"}

@app.post("/api/sentiment")
async def analyze_sentiment(request: SentimentRequest, api_key_info: Dict = Depends(get_api_key)):
    """
    Analyze sentiment of provided text
    
    This endpoint analyzes the sentiment of the provided text and returns scores
    for positive, negative, neutral, and compound sentiment.
    
    - **text**: The text to analyze
    
    Returns:
        Sentiment analysis scores
    """
    result = analyze_text_sentiment(request.text)
    return result

@app.get("/api/proposals")
async def get_proposals(api_key_info: Dict = Depends(get_api_key)):
    """
    Get all governance proposals
    
    This endpoint returns all governance proposals with their associated sentiment data.
    
    Returns:
        List of governance proposals with sentiment data
    """
    # Run the governance analysis to make sure we have data
    if not data_store.get_proposals():
        CardanoGovernance().crew().kickoff()
    
    return {
        "status": "success", 
        "message": "Governance proposals retrieved",
        "data": data_store.get_proposals()
    }

@app.get("/api/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, api_key_info: Dict = Depends(get_api_key)):
    """
    Get specific governance proposal
    
    This endpoint returns a specific governance proposal with its associated sentiment data.
    
    - **proposal_id**: ID of the proposal to retrieve
    
    Returns:
        Governance proposal with sentiment data
    """
    # Find the proposal
    proposals = data_store.get_proposals()
    proposal = next((p for p in proposals if p["id"] == proposal_id), None)
    
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    # Get sentiment data
    social_sentiment = data_store.get_social_sentiment(proposal_id)
    user_sentiment = data_store.get_user_sentiment(proposal_id)
    
    # Combine data
    result = {
        **proposal,
        "social_sentiment": social_sentiment[-1]["data"] if social_sentiment else None,
        "social_sentiment_history": social_sentiment,
        "user_sentiment": user_sentiment
    }
    
    return {
        "status": "success", 
        "message": f"Proposal {proposal_id} retrieved",
        "data": result
    }

@app.post("/api/proposals/{proposal_id}/sentiment")
async def add_user_sentiment(
    proposal_id: str, 
    request: ProposalSentimentRequest, 
    api_key_info: Dict = Depends(get_api_key)
):
    """
    Add user sentiment for a proposal
    
    This endpoint allows users to submit their sentiment about a specific governance proposal.
    
    - **proposal_id**: ID of the proposal
    - **sentiment**: Sentiment value (-1.0 to 1.0)
    
    Returns:
        Confirmation of sentiment submission
    """
    # Validate sentiment value
    if request.sentiment < -1.0 or request.sentiment > 1.0:
        raise HTTPException(status_code=400, detail="Sentiment must be between -1.0 and 1.0")
    
    # Find the proposal
    proposals = data_store.get_proposals()
    proposal = next((p for p in proposals if p["id"] == proposal_id), None)
    
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    # Save user sentiment
    data_store.save_user_sentiment(proposal_id, request.sentiment)
    
    return {
        "status": "success",
        "message": f"Sentiment for proposal {proposal_id} saved",
        "data": {
            "proposal_id": proposal_id,
            "sentiment": request.sentiment
        }
    }

@app.post("/api/payment/create")
async def create_payment(api_key_info: Dict = Depends(get_api_key)):
    """
    Create a payment request
    
    This endpoint creates a payment request for API usage.
    
    Returns:
        Payment request details
    """
    # Create payment request
    tier = api_key_info.get("tier", "free")
    amount = 10 if tier == "free" else 50  # Example pricing
    
    payment_request = create_payment_request(
        amount=amount,
        description=f"Cardano Governance API access - {tier} tier"
    )
    
    return payment_request

@app.post("/api/payment/verify")
async def verify_payment_request(request: PaymentVerificationRequest, api_key_info: Dict = Depends(get_api_key)):
    """
    Verify a payment
    
    This endpoint verifies a payment for API usage.
    
    - **request_id**: Payment request ID
    - **amount**: Payment amount
    
    Returns:
        Payment verification result
    """
    # Verify payment
    result = verify_payment(request.request_id, request.amount)
    
    return result

# Run the server
if __name__ == "__main__":
    import uvicorn
    
    # Make sure we have some initial data
    if not data_store.get_proposals():
        CardanoGovernance().crew().kickoff()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)