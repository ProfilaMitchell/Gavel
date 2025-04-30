import requests

# URL of the proposal to test
proposal_url = "https://gov.tools/budget_discussion/424"

# Headers to mimic a browser
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

# Fetch the proposal page
response = requests.get(proposal_url, headers=headers)
print(f"Status code: {response.status_code}")
print(f"Content type: {response.headers.get('content-type', 'unknown')}")
print(f"Content length: {len(response.text)} characters")

# First few lines of the response
print("\nFirst 500 characters of the response:")
print(response.text[:500])

# Save the HTML to a file
with open("raw_response.html", "w", encoding="utf-8") as f:
    f.write(response.text)

print("\nFull response saved to raw_response.html")