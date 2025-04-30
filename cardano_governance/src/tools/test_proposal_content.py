"""
Simple script to test the proposal-contents endpoint of the GovTools API.
"""

import requests
import json

# Production URL
API_URL = "https://be.pdf.gov.tools/api"

# Endpoint to test
ENDPOINT = "proposal-contents"

# Test IDs to try
TEST_IDS = ["1", "2", "3", "249"]

# Headers
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "CardanoGovernanceAgent/1.0"
}

def test_proposal_content(proposal_id):
    """
    Test the proposal-contents endpoint with a specific ID.
    """
    url = f"{API_URL}/{ENDPOINT}/{proposal_id}"
    print(f"\nTesting endpoint: {url}")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        print(f"Status code: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print("Response is valid JSON")
                
                # Save response to file
                filename = f"proposal_content_{proposal_id}.json"
                with open(filename, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"Response saved to {filename}")
                
                # Display some basic info about the response
                if isinstance(data, dict):
                    print("Response structure:")
                    for key in data.keys():
                        print(f"  - {key}")
                    
                    if "data" in data and isinstance(data["data"], dict):
                        data_obj = data["data"]
                        print("\nProposal content data:")
                        print(f"  ID: {data_obj.get('id')}")
                        
                        if "attributes" in data_obj:
                            attrs = data_obj["attributes"]
                            for key, value in attrs.items():
                                if isinstance(value, (str, int, float, bool)) and value:
                                    print(f"  {key}: {value}")
                
                return True
            except json.JSONDecodeError:
                print("Response is not valid JSON")
                print(f"Response content: {response.text[:200]}...")
        else:
            print(f"Error response: {response.text[:200]}...")
            
        return False
    except requests.RequestException as e:
        print(f"Request failed: {str(e)}")
        return False

if __name__ == "__main__":
    print("Testing GovTools proposal-contents endpoint...")
    
    # Try each test ID
    success = False
    for test_id in TEST_IDS:
        if test_proposal_content(test_id):
            success = True
    
    if not success:
        print("\nAll test IDs failed. Trying with a custom ID...")
        custom_id = input("Enter a proposal ID to test: ")
        test_proposal_content(custom_id)