# test_content_fetch.py

from govtools_api import get_content_for_proposal

if __name__ == "__main__":
    # Replace "235" with any proposal ID you want to test
    proposal_id = "249"

    content = get_content_for_proposal(proposal_id)

    if not content:
        print(f"No content found for proposal {proposal_id}")
    else:
        print(f"Proposal {proposal_id} content:")
        print("  Abstract:  ", content.get("prop_abstract", "[none]"))
        print("  Motivation:", content.get("prop_motivation", "[none]"))
        print("  Rationale: ", content.get("prop_rationale", "[none]"))
