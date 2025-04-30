import requests
import os
import json
import argparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def register_agent():
    """Register the agent with the Masumi Network Registry"""
    # Get API key from environment
    api_key = os.getenv("MASUMI_API_KEY")
    registry_url = os.getenv("MASUMI_REGISTRY_URL", "http://localhost:3001/api/agents")
    
    if not api_key:
        print("Error: MASUMI_API_KEY environment variable not set")
        print("Please add your Masumi API key to the .env file")
        return False
    
    # Agent details
    agent_data = {
        "name": "Cardano Governance Insights",
        "description": "An AI agent that provides sentiment analysis and insights for Cardano governance proposals.",
        "type": "CrewAI",
        "capabilities": [
            "Governance Proposal Tracking",
            "Bluesky Sentiment Analysis",
            "Gov.tools Comment Analysis",
            "Community Feedback Collection",
            "API Access"
        ],
        "pricing": {
            "basic": {
                "price": 10,
                "description": "Basic access with limited requests",
                "features": ["100 requests/day", "Basic sentiment analysis", "Access to all proposals"]
            },
            "pro": {
                "price": 25,
                "description": "Professional access with more features",
                "features": ["1,000 requests/day", "Advanced sentiment analysis", "Historical sentiment data", "Priority support"]
            },
            "enterprise": {
                "price": 100,
                "description": "Enterprise access with unlimited usage",
                "features": ["Unlimited requests", "Custom sentiment models", "Dedicated support", "Custom integrations"]
            }
        },
        "endpoints": [
            {
                "path": "/api/sentiment",
                "method": "POST",
                "description": "Analyze sentiment of provided text"
            },
            {
                "path": "/api/proposals",
                "method": "GET",
                "description": "Get all governance proposals"
            },
            {
                "path": "/api/proposals/{proposal_id}",
                "method": "GET",
                "description": "Get a specific governance proposal"
            },
            {
                "path": "/api/proposals/{proposal_id}/sentiment",
                "method": "POST",
                "description": "Submit user sentiment for a proposal"
            }
        ],
        "contact": {
            "email": "your-email@example.com",
            "website": "https://your-website.com"
        },
        "baseUrl": os.getenv("AGENT_BASE_URL", "http://localhost:8000")
    }
    
    # Register the agent
    try:
        response = requests.post(
            f"{registry_url}/register",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=agent_data
        )
        
        if response.status_code == 200 or response.status_code == 201:
            result = response.json()
            agent_id = result.get("agentId")
            
            print(f"Agent successfully registered with ID: {agent_id}")
            print("Adding agent ID to .env file...")
            
            # Update .env file with agent ID
            env_file = ".env"
            env_contents = ""
            
            # Read existing .env file
            if os.path.exists(env_file):
                with open(env_file, "r") as f:
                    env_contents = f.read()
            
            # Check if AGENT_ID is already in the file
            if "AGENT_ID=" in env_contents:
                # Replace existing AGENT_ID
                env_lines = env_contents.split("\n")
                new_env_lines = []
                for line in env_lines:
                    if line.startswith("AGENT_ID="):
                        new_env_lines.append(f"AGENT_ID={agent_id}")
                    else:
                        new_env_lines.append(line)
                
                env_contents = "\n".join(new_env_lines)
            else:
                # Add AGENT_ID at the end
                env_contents += f"\nAGENT_ID={agent_id}"
            
            # Write updated .env file
            with open(env_file, "w") as f:
                f.write(env_contents)
            
            print("Agent ID added to .env file")
            print("\nRegistration complete!")
            return True
        else:
            print(f"Error registering agent: {response.status_code}")
            print(response.text)
            return False
    
    except Exception as e:
        print(f"Error registering agent: {str(e)}")
        return False

def update_agent():
    """Update the agent registration with the Masumi Network Registry"""
    # Get API key and agent ID from environment
    api_key = os.getenv("MASUMI_API_KEY")
    registry_url = os.getenv("MASUMI_REGISTRY_URL", "http://localhost:3001/api/agents")
    agent_id = os.getenv("AGENT_ID")
    
    if not api_key:
        print("Error: MASUMI_API_KEY environment variable not set")
        return False
    
    if not agent_id:
        print("Error: AGENT_ID environment variable not set")
        print("Please register the agent first")
        return False
    
    # Agent details (same as registration but with updated info if needed)
    agent_data = {
        "name": "Cardano Governance Insights",
        "description": "An AI agent that provides sentiment analysis and insights for Cardano governance proposals.",
        "type": "CrewAI",
        "capabilities": [
            "Governance Proposal Tracking",
            "Bluesky Sentiment Analysis",
            "Gov.tools Comment Analysis",
            "Community Feedback Collection",
            "API Access"
        ],
        "pricing": {
            "basic": {
                "price": 10,
                "description": "Basic access with limited requests",
                "features": ["100 requests/day", "Basic sentiment analysis", "Access to all proposals"]
            },
            "pro": {
                "price": 25,
                "description": "Professional access with more features",
                "features": ["1,000 requests/day", "Advanced sentiment analysis", "Historical sentiment data", "Priority support"]
            },
            "enterprise": {
                "price": 100,
                "description": "Enterprise access with unlimited usage",
                "features": ["Unlimited requests", "Custom sentiment models", "Dedicated support", "Custom integrations"]
            }
        },
        "endpoints": [
            {
                "path": "/api/sentiment",
                "method": "POST",
                "description": "Analyze sentiment of provided text"
            },
            {
                "path": "/api/proposals",
                "method": "GET",
                "description": "Get all governance proposals"
            },
            {
                "path": "/api/proposals/{proposal_id}",
                "method": "GET",
                "description": "Get a specific governance proposal"
            },
            {
                "path": "/api/proposals/{proposal_id}/sentiment",
                "method": "POST",
                "description": "Submit user sentiment for a proposal"
            }
        ],
        "contact": {
            "email": "your-email@example.com",
            "website": "https://your-website.com"
        },
        "baseUrl": os.getenv("AGENT_BASE_URL", "http://localhost:8000")
    }
    
    # Update the agent
    try:
        response = requests.put(
            f"{registry_url}/update/{agent_id}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=agent_data
        )
        
        if response.status_code == 200:
            print(f"Agent successfully updated with ID: {agent_id}")
            return True
        else:
            print(f"Error updating agent: {response.status_code}")
            print(response.text)
            return False
    
    except Exception as e:
        print(f"Error updating agent: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Register or update Cardano Governance agent with Masumi Network")
    parser.add_argument("action", choices=["register", "update"], help="Action to perform")
    
    args = parser.parse_args()
    
    if args.action == "register":
        register_agent()
    elif args.action == "update":
        update_agent()