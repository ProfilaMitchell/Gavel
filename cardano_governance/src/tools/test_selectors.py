"""
Test script for HTML selectors on gov.tools proposal page.
Run this script to verify our selectors before updating the main code.
"""

import requests
from bs4 import BeautifulSoup
import json
import re

# URL of the proposal to test
proposal_id = "424"
proposal_url = f"https://gov.tools/budget_discussion/{proposal_id}"

# Headers to mimic a browser
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

def test_selectors():
    print(f"Testing selectors on proposal: {proposal_url}")
    
    try:
        # Fetch the proposal page
        response = requests.get(proposal_url, headers=headers)
        response.raise_for_status()
        
        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Test title selectors
        print("\n--- TITLE SELECTORS ---")
        title_selectors = [
            ('h1.proposal-title', soup.select('h1.proposal-title')),
            ('h1', soup.select('h1')),
            ('div.proposal-header h1', soup.select('div.proposal-header h1')),
            ('.proposal-title', soup.select('.proposal-title')),
            ('h1:first-of-type', soup.select('h1:first-of-type')),
        ]
        
        for selector, elements in title_selectors:
            if elements:
                print(f"✅ Selector '{selector}' found {len(elements)} elements")
                for i, elem in enumerate(elements[:2]):  # Show up to 2 elements
                    print(f"  Element #{i+1}: {elem.text.strip()[:50]}...")
            else:
                print(f"❌ Selector '{selector}' found no elements")
        
        # Test author selectors
        print("\n--- AUTHOR SELECTORS ---")
        author_selectors = [
            ('div.proposal-author', soup.select('div.proposal-author')),
            ('span.author', soup.select('span.author')),
            ('.proposal-meta .author', soup.select('.proposal-meta .author')),
            ('h1 + div', soup.select('h1 + div')),
        ]
        
        for selector, elements in author_selectors:
            if elements:
                print(f"✅ Selector '{selector}' found {len(elements)} elements")
                for i, elem in enumerate(elements[:2]):
                    print(f"  Element #{i+1}: {elem.text.strip()[:50]}...")
            else:
                print(f"❌ Selector '{selector}' found no elements")
        
        # Test budget category selectors
        print("\n--- BUDGET CATEGORY SELECTORS ---")
        category_selectors = [
            ('div:contains("Budget category") + div', [e.find_next('div') for e in soup.find_all('div', text=re.compile('Budget category'))]),
            ('.metadata-section:contains("Budget category") .metadata-value', soup.select('.metadata-section:contains("Budget category") .metadata-value')),
            ('dt:contains("Budget category") + dd', soup.select('dt:contains("Budget category") + dd')),
        ]
        
        for selector, elements in category_selectors:
            if elements and all(elements):  # Filter out None values
                elements = [e for e in elements if e]
                print(f"✅ Selector '{selector}' found {len(elements)} elements")
                for i, elem in enumerate(elements[:2]):
                    print(f"  Element #{i+1}: {elem.text.strip()[:50]}...")
            else:
                print(f"❌ Selector '{selector}' found no elements")
        
        # Test for Budget category with a different approach
        category_labels = soup.find_all(string=re.compile('Budget category'))
        if category_labels:
            print(f"✅ Found {len(category_labels)} budget category labels")
            for i, label in enumerate(category_labels[:2]):
                print(f"  Label #{i+1}: {label}")
                parent = label.parent
                print(f"  Parent: {parent.name} {parent.get('class')}")
                next_sibling = parent.find_next_sibling()
                if next_sibling:
                    print(f"  Next sibling: {next_sibling.name} {next_sibling.get('class')} - {next_sibling.text.strip()[:50]}...")
                next_element = parent.find_next()
                if next_element and next_element != next_sibling:
                    print(f"  Next element: {next_element.name} {next_element.get('class')} - {next_element.text.strip()[:50]}...")
        
        # Test problem statement selectors
        print("\n--- PROBLEM STATEMENT SELECTORS ---")
        problem_selectors = [
            ('div:contains("Problem Statement") + div', [e.find_next('div') for e in soup.find_all('div', text=re.compile('Problem Statement'))]),
            ('.problem-statement', soup.select('.problem-statement')),
            ('h3:contains("Problem Statement") + p', soup.select('h3:contains("Problem Statement") + p')),
        ]
        
        for selector, elements in problem_selectors:
            if elements and all(elements):
                elements = [e for e in elements if e]
                print(f"✅ Selector '{selector}' found {len(elements)} elements")
                for i, elem in enumerate(elements[:2]):
                    print(f"  Element #{i+1}: {elem.text.strip()[:50]}...")
            else:
                print(f"❌ Selector '{selector}' found no elements")
        
        # Test for Problem Statement with a different approach
        problem_labels = soup.find_all(string=re.compile('Problem Statement'))
        if problem_labels:
            print(f"✅ Found {len(problem_labels)} problem statement labels")
            for i, label in enumerate(problem_labels[:2]):
                print(f"  Label #{i+1}: {label}")
                parent = label.parent
                print(f"  Parent: {parent.name} {parent.get('class')}")
                next_sibling = parent.find_next_sibling()
                if next_sibling:
                    print(f"  Next sibling: {next_sibling.name} {next_sibling.get('class')} - {next_sibling.text.strip()[:50]}...")
                next_element = parent.find_next()
                if next_element and next_element != next_sibling:
                    print(f"  Next element: {next_element.name} {next_element.get('class')} - {next_element.text.strip()[:50]}...")
        
        # Test comments section
        print("\n--- COMMENTS SECTION SELECTORS ---")
        comments_selectors = [
            ('#comments', soup.select('#comments')),
            ('.comments-section', soup.select('.comments-section')),
            ('.comment', soup.select('.comment')),
            ('div[id*="comment"]', soup.select('div[id*="comment"]')),
        ]
        
        for selector, elements in comments_selectors:
            if elements:
                print(f"✅ Selector '{selector}' found {len(elements)} elements")
                for i, elem in enumerate(elements[:2]):
                    print(f"  Element #{i+1}: {elem.name} {elem.get('class')} - {elem.text.strip()[:50]}...")
            else:
                print(f"❌ Selector '{selector}' found no elements")
        
        # Test poll results
        print("\n--- POLL RESULTS SELECTORS ---")
        poll_selectors = [
            ('.poll-results', soup.select('.poll-results')),
            ('div:contains("Poll Results")', soup.find_all('div', text=re.compile('Poll Results'))),
            ('div:contains("Yes:").poll-option', soup.find_all('div', text=re.compile('Yes:'), class_='poll-option')),
        ]
        
        for selector, elements in poll_selectors:
            if elements:
                print(f"✅ Selector '{selector}' found {len(elements)} elements")
                for i, elem in enumerate(elements[:2]):
                    if hasattr(elem, 'text'):
                        print(f"  Element #{i+1}: {elem.name} {elem.get('class')} - {elem.text.strip()[:50]}...")
                    else:
                        print(f"  Element #{i+1}: [NavigableString] - {str(elem)[:50]}...")
            else:
                print(f"❌ Selector '{selector}' found no elements")
        
        # Look for poll results mentions
        poll_text = soup.find_all(string=lambda s: s and ('Poll Results' in s or 'Yes:' in s or 'No:' in s))
        if poll_text:
            print(f"✅ Found {len(poll_text)} poll-related text nodes")
            for i, text in enumerate(poll_text[:5]):
                print(f"  Text #{i+1}: {str(text)[:50]}...")
                print(f"  Parent: {text.parent.name} {text.parent.get('class')}")
        
        # Save the HTML to a file for reference
        with open("test_proposal_page.html", "w", encoding="utf-8") as f:
            f.write(soup.prettify())
        
        print("\nHTML saved to test_proposal_page.html for further inspection")
        
    except Exception as e:
        print(f"Error testing selectors: {str(e)}")

if __name__ == "__main__":
    test_selectors()