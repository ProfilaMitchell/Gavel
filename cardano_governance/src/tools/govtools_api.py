"""
GovTools API client module - Based on official OpenAPI documentation.

This module provides functions to interact with the GovTools RESTful API
to fetch proposal data and related information.
"""

import requests
import json
import logging
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API configuration
# For production, use the actual production URL
# BASE_URL = "https://api.gov.tools"
# For development, use the development URL from the spec
BASE_URL = "https://be.pdf.gov.tools/api"

# Headers for API requests
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "CardanoGovernanceAgent/1.0"
}

class GovToolsAPIError(Exception):
    """Exception raised for GovTools API errors"""
    pass

def get_proposals(limit: int = 25, offset: int = 0, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """
    Fetch a list of proposals from the GovTools API, with a fallback if 'populate' fails.
    
    Args:
        limit: Maximum number of proposals to fetch
        offset: Offset for pagination
        filters: Optional filters to apply
        
    Returns:
        List of proposal objects
        
    Raises:
        GovToolsAPIError: If the API request fails
    """
    url = f"{BASE_URL}/proposals"

    # Base params (no populate yet)
    params = {
        "pagination[limit]": limit,
        "pagination[start]": offset,
        "sort": "createdAt:desc"
    }
    # Merge in any filters
    if filters:
        for key, value in filters.items():
            params[f"filters[{key}]"] = value

    # First attempt: with related data
    try:
        params["populate"] = "content,gov_action_type"
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # If Strapi returns a 500 on populate, drop it and retry once
        if response.status_code == 500:
            logger.warning("Strapi 500 error on populate; retrying without populate.")
            params.pop("populate", None)
            response = requests.get(url, headers=HEADERS, params=params, timeout=10)
            response.raise_for_status()
        else:
            error_msg = f"API request failed: {e}"
            logger.error(error_msg)
            raise GovToolsAPIError(error_msg)

    # Parse JSON
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse API response: {e}"
        logger.error(error_msg)
        raise GovToolsAPIError(error_msg)

    # (Optional) dump raw JSON for debugging
    with open("proposals_response.json", "w") as f:
        json.dump(data, f, indent=2)
        logger.info("Saved raw proposals_response.json for inspection")

    # Validate structure
    if not isinstance(data, dict) or "data" not in data:
        logger.warning("Unexpected response format: 'data' key not found")
        return []

    # Process each proposal
    processed_proposals = []
    for item in data["data"]:
        attributes  = item.get("attributes", {})
        proposal_id = item.get("id")

        # Extract any embedded content (if populate succeeded)
        content = None
        content_data = attributes.get("content", {})
        if isinstance(content_data, dict) and "data" in content_data:
            content = content_data["data"].get("attributes", {})

        # Build your output dict
        proposal = {
            "id":            proposal_id,
            "url":           f"{BASE_URL}/proposals/{proposal_id}",
            "user_id":       attributes.get("user_id"),
            "likes":         attributes.get("prop_likes", 0),
            "dislikes":      attributes.get("prop_dislikes", 0),
            "poll_active":   attributes.get("prop_poll_active", False),
            "comment_count": attributes.get("prop_comments_number", 0),
            "created_at":    attributes.get("createdAt"),
            "updated_at":    attributes.get("updatedAt"),
            # text fields (from content if available; else blank)
            "status":        "Active",
            "title":         content.get("prop_name", "Untitled") if content else "Untitled",
            "description":   content.get("prop_abstract", "")    if content else "",
            "date_created":  attributes.get("createdAt"),
            "date_updated":  attributes.get("updatedAt"),
            "category":      "Unknown",
        }
        processed_proposals.append(proposal)

    return processed_proposals


def get_proposal_by_id(proposal_id: str) -> Dict[str, Any]:
    """
    Fetch a specific proposal by ID from the GovTools API.
    
    Args:
        proposal_id: ID of the proposal to fetch
        
    Returns:
        Proposal object with detailed information
        
    Raises:
        GovToolsAPIError: If the API request fails
    """
    try:
        url = f"{BASE_URL}/proposals/{proposal_id}"
        
        # Add population of related data
        params = {
            "populate": "content,gov_action_type"
        }
        
        logger.info(f"Fetching proposal {proposal_id} from {url}")
        
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        
        # Parse the JSON response
        data = response.json()
        
        # Save the raw response for debugging
        with open(f"proposal_{proposal_id}_response.json", "w") as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Raw response saved to proposal_{proposal_id}_response.json")
        
        # Process the proposal into our standard format
        if not isinstance(data, dict) or "data" not in data:
            logger.warning("Unexpected response format: 'data' key not found")
            raise GovToolsAPIError("Invalid API response format")
        
        item = data["data"]
        attributes = item.get("attributes", {})
        
        # OLD LOGIC: Get content data if available
        content = None
        content_data = attributes.get("content", {})
        if isinstance(content_data, dict) and "data" in content_data:
            content_attributes = content_data["data"].get("attributes", {})
            content = content_attributes

        logger.info(f"Explicitly fetching content details for proposal {proposal_id} via get_content_for_proposal.")
        try:
            # Call the separate function that queries /proposal-contents
            content = get_content_for_proposal(proposal_id) # This returns the attributes dict directly
            if not content:
                 logger.warning(f"No content record found via get_content_for_proposal for ID {proposal_id}.")
                 content = {} # Ensure content is an empty dict if nothing found
        except Exception as content_e:
            logger.error(f"Error calling get_content_for_proposal for ID {proposal_id}: {content_e}", exc_info=True)
            content = {} # Ensure content is an empty dict on error
        
        # Get the user_id as the author_id
        author_id = attributes.get("user_id")
        
        # Build the processed proposal object with more detailed information
        proposal = {
            "id": proposal_id,
            "url": f"{BASE_URL}/proposals/{proposal_id}",
            "user_id": attributes.get("user_id"),
            "likes": attributes.get("prop_likes", 0),
            "dislikes": attributes.get("prop_dislikes", 0),
            "poll_active": attributes.get("prop_poll_active", False),
            "comment_count": attributes.get("prop_comments_number", 0),
            "created_at": attributes.get("createdAt"),
            "updated_at": attributes.get("updatedAt"),
            
            # Add content information if available
            "title": content.get("prop_name", "Untitled") if content else "Untitled",
            "abstract": content.get("prop_abstract", "") if content else "",
            "motivation": content.get("prop_motivation", "") if content else "",
            "rationale": content.get("prop_rationale", "") if content else "",
            "category": content.get("gov_action_type_id", "Unknown"),
            
            # Add compatibility with expected format
            "status": "Active",  # Default status
            "description": f"{content.get('prop_abstract', '')}\n\n{content.get('prop_motivation', '')}",
            "date_created": attributes.get("createdAt"),
            "date_updated": attributes.get("updatedAt"),
            
            # Add placeholders for data we'll fetch separately
            "comments": [],
            "poll_results": {}
        }
        
        # Fetch comments for this proposal
        proposal["comments"] = get_comments_for_proposal(proposal_id)
        
        # Process comments with author awareness
        author_id_for_comments = attributes.get("user_id")
        proposal["processed_comments"] = process_comments_for_sentiment(proposal["comments"], author_id_for_comments)
        
        # Fetch poll results for this proposal
        proposal["poll_results"] = get_poll_for_proposal(proposal_id)
        
        return proposal
        
    except requests.RequestException as e:
        error_msg = f"API request failed: {str(e)}"
        logger.error(error_msg)
        raise GovToolsAPIError(error_msg)
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse API response: {str(e)}"
        logger.error(error_msg)
        raise GovToolsAPIError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg)
        raise GovToolsAPIError(error_msg)


def get_comments_for_proposal(proposal_id: str) -> List[Dict[str, Any]]:
    """
    Fetch comments for a specific proposal and filter out automated/duplicate messages.
    
    Args:
        proposal_id: ID of the proposal
        
    Returns:
        List of filtered comment objects
        
    Raises:
        GovToolsAPIError: If the API request fails
    """
    try:
        url = f"{BASE_URL}/comments"
        
        # Filter comments for this proposal
        params = {
            "filters[proposal_id][$eq]": proposal_id,
            "sort": "createdAt:desc",  # Most recent first
            "pagination[limit]": 100  # Get up to 100 comments
        }
        
        logger.info(f"Fetching comments for proposal {proposal_id} from {url}")
        
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        
        # Parse the JSON response
        data = response.json()
        
        # Process the comments into our standard format
        all_comments = []
        
        if not isinstance(data, dict) or "data" not in data:
            logger.warning("Unexpected response format: 'data' key not found")
            return []
        
        for item in data["data"]:
            attributes = item.get("attributes", {})
            
            # Determine if this is a DRep comment (simplified approach)
            # In a real implementation, you would check against a list of DReps
            is_drep = False  # Default to False since we can't determine from API alone
            
            comment = {
                "id": item.get("id"),
                "author": attributes.get("user_id", "Unknown"),
                "text": attributes.get("comment_text", ""),
                "date": attributes.get("createdAt"),
                "is_drep": is_drep,
                "drep_address": None,  # Would need additional API call to get this
                "likes": 0  # Not provided in API
            }
            
            all_comments.append(comment)
        
        # Filter out automated and duplicate comments
        filtered_comments = []
        seen_texts = set()
        
        # Common automated texts to filter out
        common_automated_messages = [
            "thanks for voting",
            "thank you for voting", 
            "thank you for your vote",
            "thanks for your vote",
            "voted yes",
            "voted no",
            "i vote yes", 
            "i vote no"
        ]
        
        for comment in all_comments:
            text = comment.get("text", "").lower().strip()
            
            # Skip empty comments
            if not text:
                continue
                
            # Skip very short comments (likely just "Yes" or "No")
            if len(text) < 5:
                continue
                
            # Skip common automated messages
            if any(auto_msg in text for auto_msg in common_automated_messages):
                continue
                
            # Skip duplicates
            if text in seen_texts:
                continue
                
            seen_texts.add(text)
            filtered_comments.append(comment)
        
        logger.info(f"Filtered comments: {len(all_comments)} original, {len(filtered_comments)} after filtering")
        
        return filtered_comments
        
    except requests.RequestException as e:
        error_msg = f"API request failed when fetching comments: {str(e)}"
        logger.error(error_msg)
        return []  # Return empty list on error instead of failing
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse API response when fetching comments: {str(e)}"
        logger.error(error_msg)
        return []
    except Exception as e:
        error_msg = f"Unexpected error when fetching comments: {str(e)}"
        logger.error(error_msg)
        return []


def filter_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter comments to remove duplicates and automated messages.
    
    Args:
        comments: List of comment objects
        
    Returns:
        Filtered list of comment objects
    """
    filtered_comments = []
    seen_texts = set()
    
    # Common automated texts to filter out
    common_automated_messages = [
        "thanks for voting",
        "thank you for voting",
        "thank you for your vote",
        "thanks for your vote",
        "voted yes",
        "voted no",
        "i vote yes", 
        "i vote no"
    ]
    
    for comment in comments:
        text = comment.get("text", "").lower().strip()
        
        # Skip empty comments
        if not text:
            continue
            
        # Skip very short comments (likely just "Yes" or "No")
        if len(text) < 5:
            continue
            
        # Skip common automated messages
        if any(auto_msg in text for auto_msg in common_automated_messages):
            continue
            
        # Skip duplicates
        if text in seen_texts:
            continue
            
        seen_texts.add(text)
        filtered_comments.append(comment)
    
    logger.info(f"Filtered comments: {len(comments)} original, {len(filtered_comments)} after filtering")
    return filtered_comments

def process_comments_for_sentiment(comments: List[Dict[str, Any]], proposal_author_id: str = None) -> Dict[str, Any]:
    """
    Process comments for sentiment analysis with author awareness and duplicate removal.
    
    Args:
        comments: List of comment objects
        proposal_author_id: ID of the proposal author, if known
        
    Returns:
        Dict with processed comments and metadata
    """
    processed_result = {
        "all_comments": [],
        "author_comments": [],
        "community_comments": [],
        "drep_comments": [],
        "filtered_out": 0,
        "duplicate_count": 0,
        "thank_you_count": 0
    }
    
    # Track unique comments to filter duplicates
    seen_comments = set()
    
    # Common thank you messages with limited sentiment value
    thank_you_patterns = [
        "thanks for voting",
        "thank you for voting", 
        "thank you for your vote",
        "thanks for your vote",
        "voted yes",
        "voted no",
        "i vote yes", 
        "i vote no"
    ]
    
    for comment in comments:
        text = comment.get("text", "").lower().strip()
        author_id = comment.get("author")
        is_author = (proposal_author_id and author_id == proposal_author_id)
        is_drep = comment.get("is_drep", False)
        
        # Skip empty comments
        if not text:
            processed_result["filtered_out"] += 1
            continue
            
        # Detect thank you/voting messages but don't automatically filter them
        is_thank_you = any(pattern in text for pattern in thank_you_patterns)
        if is_thank_you:
            processed_result["thank_you_count"] += 1
        
        # Create a unique identifier for this comment (author + text)
        comment_id = f"{author_id}:{text}"
        
        # Check for duplicate comments
        if comment_id in seen_comments:
            processed_result["duplicate_count"] += 1
            continue
            
        seen_comments.add(comment_id)
        
        # Add metadata about the comment source
        comment_with_metadata = {
            **comment,
            "is_author": is_author,
            "is_thank_you": is_thank_you
        }
        
        # Add to the appropriate categories
        processed_result["all_comments"].append(comment_with_metadata)
        
        if is_author:
            processed_result["author_comments"].append(comment_with_metadata)
        elif is_drep:
            processed_result["drep_comments"].append(comment_with_metadata)
        else:
            processed_result["community_comments"].append(comment_with_metadata)
    
    logger.info(f"Processed {len(comments)} comments: {len(processed_result['all_comments'])} unique comments, {processed_result['duplicate_count']} duplicates, {processed_result['thank_you_count']} thank you messages")
    
    return processed_result


def get_poll_for_proposal(proposal_id: str) -> Dict[str, Any]:
    """
    Fetch poll results for a specific proposal.
    
    Args:
        proposal_id: ID of the proposal
        
    Returns:
        Poll results object
        
    Raises:
        GovToolsAPIError: If the API request fails
    """
    try:
        url = f"{BASE_URL}/polls"
        
        # Filter polls for this proposal
        params = {
            "filters[proposal_id][$eq]": proposal_id
        }
        
        logger.info(f"Fetching poll for proposal {proposal_id} from {url}")
        
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        
        # Parse the JSON response
        data = response.json()
        
        # Process the poll data into our standard format
        if not isinstance(data, dict) or "data" not in data:
            logger.warning("Unexpected response format: 'data' key not found")
            return {}
        
        # Get the first poll (should only be one per proposal)
        polls = data["data"]
        if not polls:
            return {}
        
        poll_item = polls[0]
        attributes = poll_item.get("attributes", {})
        
        poll_results = {
            "question": "Do you support this proposal?",  # Default question
            "total_votes": attributes.get("poll_yes", 0) + attributes.get("poll_no", 0),
            "yes_percentage": calculate_percentage(attributes.get("poll_yes", 0), 
                                                 attributes.get("poll_yes", 0) + attributes.get("poll_no", 0)),
            "no_percentage": calculate_percentage(attributes.get("poll_no", 0), 
                                                attributes.get("poll_yes", 0) + attributes.get("poll_no", 0)),
            "is_active": attributes.get("is_poll_active", False),
            "start_date": attributes.get("poll_start_dt")
        }
        
        return poll_results
        
    except requests.RequestException as e:
        error_msg = f"API request failed when fetching poll: {str(e)}"
        logger.error(error_msg)
        return {}  # Return empty dict on error instead of failing
    except json.JSONDecodeError as e:
        error_msg = f"Failed to parse API response when fetching poll: {str(e)}"
        logger.error(error_msg)
        return {}
    except Exception as e:
        error_msg = f"Unexpected error when fetching poll: {str(e)}"
        logger.error(error_msg)
        return {}

def calculate_percentage(part: int, total: int) -> int:
    """Calculate percentage safely, handling division by zero"""
    if total == 0:
        return 0
    return int((part / total) * 100)

def get_budget_proposal(proposal_id: str) -> Dict[str, Any]:
    """
    Alias for get_proposal_by_id for compatibility with existing code.
    """
    return get_proposal_by_id(proposal_id)

def get_budget_proposals(limit: int = 25, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Alias for get_proposals for compatibility with existing code.
    """
    return get_proposals(limit, offset)

# Simple test function
def test_api():
    """Test the API functionality"""
    try:
        # Test getting a list of proposals
        proposals = get_proposals(limit=5)
        print(f"Successfully retrieved {len(proposals)} proposals")
        
        if proposals:
            # Test getting a specific proposal
            proposal_id = proposals[0]["id"]
            proposal = get_proposal_by_id(proposal_id)
            print(f"Successfully retrieved proposal: {proposal['title']}")
            print(f"Number of comments: {len(proposal['comments'])}")
            print(f"Poll results: {proposal['poll_results']}")
            
    except GovToolsAPIError as e:
        print(f"API test failed: {str(e)}")

if __name__ == "__main__":
    test_api()

def get_content_for_proposal(proposal_id: str) -> Dict[str, Any]:
    """
    Fetch the full text fields (abstract, motivation, rationale, etc.)
    for the given proposal_id, by filtering the proposal-contents table.
    Returns a dict of attributes, or an empty dict if none found.
    """
    url = f"{BASE_URL}/proposal-contents"
    # Strapi filter syntax: only return rows whose proposal_id matches ours
    params = {
        "filters[proposal_id][$eq]": proposal_id
    }

    # Make the HTTP request
    response = requests.get(url, headers=HEADERS, params=params, timeout=10)
    # Raise an exception on any 4xx/5xx
    response.raise_for_status()

    payload = response.json()
    items   = payload.get("data", [])

    if not items:
        # No content record found
        return {}

    # We expect exactly one matching record: take the first
    attributes = items[0].get("attributes", {})
    return attributes
