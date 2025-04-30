# test_comments_fetch.py

from govtools_api import get_comments_for_proposal

if __name__ == "__main__":
    # Use the same proposal ID you tested above
    proposal_id = "249"

    comments = get_comments_for_proposal(proposal_id)

    if not comments:
        print(f"No comments found for proposal {proposal_id}")
    else:
        print(f"Proposal {proposal_id} has {len(comments)} comments. Showing up to 5:")
        for c in comments[:5]:
            print(f" - [{c['date']}] {c['author']}: {c['text'][:80]}...")
