import govtools_api


def explore_proposals(limit=50, offset=0):
    """
    Fetch proposals and their related content IDs, then compare with proposal IDs.
    """
    # Fetch a batch of proposals
    proposals = govtools_api.get_proposals(limit=limit, offset=offset)
    print(f"Fetched {len(proposals)} proposals (limit={limit}, offset={offset})")

    mismatches = []
    for p in proposals:
        prop_id = p.get("id")
        # In the raw data, the content ID is nested under relationship or in attributes
        raw = p.get("_raw", {})  # if your client stores raw JSON
        # Fallback: use attributes.content.data.id if present
        data = raw.get("data", {})
        rel = data.get("relationships", {})
        content_data = rel.get("content", {}).get("data")
        content_id = content_data.get("id") if content_data else None
        print(f"Proposal {prop_id} → content {content_id}")
        if content_id and str(content_id) != str(prop_id):
            mismatches.append((prop_id, content_id))

    if mismatches:
        print("Mismatched IDs:")
        for prop_id, content_id in mismatches:
            print(f"  - Proposal ID {prop_id} has content ID {content_id}")
    else:
        print("All proposals matched content IDs.")


def inspect_content_details(content_id):
    """
    Fetch a specific proposal-content record and print its attributes.
    """
    content = govtools_api.get_proposal_contents_by_id(str(content_id))
    print(json.dumps(content, indent=2))


def fetch_comments(prop_id, limit=20):
    """
    Fetch and display comments for a given proposal.
    """
    comments = govtools_api.get_comments_for_proposal(str(prop_id))
    print(f"Proposal {prop_id} has {len(comments)} comments:")
    for c in comments[:limit]:
        print(f"- [{c['date']}] {c['author']}: {c['text'][:80]}...")


if __name__ == "__main__":
    # Example usage
    explore_proposals(limit=25, offset=0)
    # For any mismatched content, inspect details:
    # inspect_content_details(249)
    # Fetch comments for a sample proposal:
    # fetch_comments(249)
