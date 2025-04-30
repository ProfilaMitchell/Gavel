"""
Test script for the GovTools API client.
Run this script to test the API endpoints and understand the response structure.
"""

import sys
import os
import json

# Add the tools directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))

# Import the API client
from govtools_api import get_budget_proposal, get_budget_proposals, GovToolsAPIError

def test_get_proposal():
    """Test fetching a single budget proposal"""
    proposal_id = "424"  # Example proposal ID
    
    try:
        print(f"Fetching proposal {proposal_id}...")
        proposal = get_budget_proposal(proposal_id)
        
        print(f"Successfully fetched proposal: {proposal.get('title', 'Unknown Title')}")
        print(f"Author: {proposal.get('author', 'Unknown')}")
        print(f"Budget Category: {proposal.get('budget_category', 'Unknown')}")
        
        # Print the full proposal data
        print("\nFull proposal data:")
        print(json.dumps(proposal, indent=2))
        
        return True
    except GovToolsAPIError as e:
        print(f"Error: {e}")
        return False

def test_get_proposals():
    """Test fetching a list of budget proposals"""
    try:
        print("Fetching budget proposals (limit=5)...")
        proposals = get_budget_proposals(limit=5)
        
        print(f"Successfully fetched {len(proposals)} proposals:")
        
        for i, proposal in enumerate(proposals):
            print(f"\n{i+1}. {proposal.get('title', 'Unknown Title')}")
            print(f"   ID: {proposal.get('id', 'Unknown')}")
            print(f"   Author: {proposal.get('author', 'Unknown')}")
            print(f"   Category: {proposal.get('budget_category', 'Unknown')}")
        
        # Print the full list data
        print("\nFull proposals data:")
        print(json.dumps(proposals, indent=2))
        
        return True
    except GovToolsAPIError as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print("Testing GovTools API client...")
    
    # Test getting a single proposal
    print("\n=== Testing get_budget_proposal ===")
    test_get_proposal()
    
    # Test getting a list of proposals
    print("\n=== Testing get_budget_proposals ===")
    test_get_proposals()