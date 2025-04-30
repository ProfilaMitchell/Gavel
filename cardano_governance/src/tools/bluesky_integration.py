import requests
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Load environment variables
load_dotenv()

# Initialize sentiment analyzer
sentiment_analyzer = SentimentIntensityAnalyzer()

class BlueskyClient:
    """Client for interacting with the Bluesky API"""
    
    def __init__(self):
        self.base_url = "https://bsky.social/xrpc"
        self.session = requests.Session()
        self.auth_token = None
        self.refresh_token = None
    
    def authenticate(self):
        """Authenticate with Bluesky"""
        identifier = os.getenv("BLUESKY_IDENTIFIER")
        password = os.getenv("BLUESKY_PASSWORD")
        
        if not identifier or not password:
            print("Error: BLUESKY_IDENTIFIER or BLUESKY_PASSWORD not set in .env file")
            return False
        
        try:
            response = self.session.post(
                f"{self.base_url}/com.atproto.server.createSession",
                json={"identifier": identifier, "password": password}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.auth_token = data.get("accessJwt")
                self.refresh_token = data.get("refreshJwt")
                self.session.headers.update({"Authorization": f"Bearer {self.auth_token}"})
                return True
            else:
                print(f"Authentication failed: {response.status_code}")
                print(response.text)
                return False
                
        except Exception as e:
            print(f"Error during authentication: {str(e)}")
            return False
    
    def search_posts(self, query, limit=50):
        """Search for posts containing the query"""
        if not self.auth_token:
            if not self.authenticate():
                return []
        
        try:
            response = self.session.get(
                f"{self.base_url}/app.bsky.feed.searchPosts",
                params={"q": query, "limit": limit}
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("posts", [])
            else:
                print(f"Search failed: {response.status_code}")
                print(response.text)
                return []
                
        except Exception as e:
            print(f"Error during search: {str(e)}")
            return []

def fetch_bluesky_posts(search_terms, limit=50):
    """Fetch posts from Bluesky related to search terms"""
    client = BlueskyClient()
    
    if not client.authenticate():
        return []
    
    # Combine search terms into a query
    query = ' OR '.join([f'"{term}"' for term in search_terms])
    
    # Search for posts
    posts = client.search_posts(query, limit=limit)
    
    # Extract relevant information
    formatted_posts = []
    for post in posts:
        formatted_posts.append({
            "id": post.get("uri", ""),
            "text": post.get("record", {}).get("text", ""),
            "created_at": post.get("indexedAt", ""),
            "author": post.get("author", {}).get("handle", ""),
            "likes": post.get("likeCount", 0),
            "replies": post.get("replyCount", 0)
        })
    
    return formatted_posts

def analyze_bluesky_sentiment(search_terms, limit=50):
    """Analyze sentiment of Bluesky posts related to search terms"""
    posts = fetch_bluesky_posts(search_terms, limit=limit)
    
    if not posts:
        return {
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "compound": 0,
            "post_count": 0,
            "search_terms": search_terms
        }
    
    # Analyze sentiment of each post
    sentiments = []
    for post in posts:
        sentiment = sentiment_analyzer.polarity_scores(post["text"])
        sentiments.append(sentiment)
    
    # Calculate average sentiment
    avg_sentiment = {
        "positive": sum(s["pos"] for s in sentiments) / len(sentiments),
        "negative": sum(s["neg"] for s in sentiments) / len(sentiments),
        "neutral": sum(s["neu"] for s in sentiments) / len(sentiments),
        "compound": sum(s["compound"] for s in sentiments) / len(sentiments),
        "post_count": len(posts),
        "search_terms": search_terms,
        "posts": posts[:10]  # Include first 10 posts for reference
    }
    
    return avg_sentiment

def fetch_govtools_comments(proposal_id):
    """
    Fetch comments from gov.tools for a specific proposal
    
    In a real implementation, this would use web scraping or the gov.tools API if available
    """
    # This is a simplified mock implementation
    # In reality, you would implement proper web scraping or API calls
    
    # Example comments data structure
    example_comments = [
        {
            "id": "c1",
            "text": "I strongly support this proposal as it addresses key issues in the voting mechanism.",
            "author": "CardanoFan42",
            "date": "2024-03-16T10:30:00Z",
            "votes": 15
        },
        {
            "id": "c2",
            "text": "While the idea has merit, I'm concerned about the implementation timeline.",
            "author": "ADAHodler",
            "date": "2024-03-17T08:45:00Z",
            "votes": 8
        },
        {
            "id": "c3",
            "text": "This is exactly what we need to improve governance participation.",
            "author": "StakePoolOperator",
            "date": "2024-03-18T14:20:00Z",
            "votes": 23
        }
    ]
    
    # In a real implementation, you would fetch actual comments based on the proposal ID
    return example_comments

def analyze_govtools_sentiment(proposal_id):
    """Analyze sentiment of gov.tools comments for a specific proposal"""
    comments = fetch_govtools_comments(proposal_id)
    
    if not comments:
        return {
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "compound": 0,
            "comment_count": 0
        }
    
    # Analyze sentiment of each comment
    sentiments = []
    for comment in comments:
        sentiment = sentiment_analyzer.polarity_scores(comment["text"])
        sentiments.append(sentiment)
    
    # Calculate average sentiment
    avg_sentiment = {
        "positive": sum(s["pos"] for s in sentiments) / len(sentiments),
        "negative": sum(s["neg"] for s in sentiments) / len(sentiments),
        "neutral": sum(s["neu"] for s in sentiments) / len(sentiments),
        "compound": sum(s["compound"] for s in sentiments) / len(sentiments),
        "comment_count": len(comments),
        "comments": comments[:10]  # Include first 10 comments for reference
    }
    
    return avg_sentiment

def combine_sentiment_sources(bluesky_sentiment, govtools_sentiment):
    """Combine sentiment from multiple sources into a weighted average"""
    # Get the count of data points from each source
    bluesky_count = bluesky_sentiment.get("post_count", 0)
    govtools_count = govtools_sentiment.get("comment_count", 0)
    
    # If no data from either source, return neutral sentiment
    if bluesky_count == 0 and govtools_count == 0:
        return {
            "positive": 0,
            "negative": 0,
            "neutral": 1.0,
            "compound": 0,
            "sources": {
                "bluesky": bluesky_sentiment,
                "govtools": govtools_sentiment
            }
        }
    
    # Calculate weights based on data point counts
    total_count = bluesky_count + govtools_count
    bluesky_weight = bluesky_count / total_count if total_count > 0 else 0
    govtools_weight = govtools_count / total_count if total_count > 0 else 0
    
    # Calculate weighted average
    combined_sentiment = {
        "positive": (bluesky_sentiment.get("positive", 0) * bluesky_weight +
                    govtools_sentiment.get("positive", 0) * govtools_weight),
        "negative": (bluesky_sentiment.get("negative", 0) * bluesky_weight +
                    govtools_sentiment.get("negative", 0) * govtools_weight),
        "neutral": (bluesky_sentiment.get("neutral", 0) * bluesky_weight +
                   govtools_sentiment.get("neutral", 0) * govtools_weight),
        "compound": (bluesky_sentiment.get("compound", 0) * bluesky_weight +
                    govtools_sentiment.get("compound", 0) * govtools_weight),
        "total_sources": total_count,
        "sources": {
            "bluesky": bluesky_sentiment,
            "govtools": govtools_sentiment
        }
    }
    
    return combined_sentiment

def get_proposal_sentiment(proposal_id, proposal_title, proposal_description):
    """Get combined sentiment for a proposal from all available sources"""
    # Generate search terms from the proposal title and description
    search_terms = [
        proposal_title,
        # Extract key phrases from description
        *[phrase.strip() for phrase in proposal_description.split('.') if len(phrase.strip()) > 20][:3]
    ]
    
    # Get sentiment from each source
    bluesky_sentiment = analyze_bluesky_sentiment(search_terms)
    govtools_sentiment = analyze_govtools_sentiment(proposal_id)
    
    # Combine sentiment from all sources
    combined_sentiment = combine_sentiment_sources(bluesky_sentiment, govtools_sentiment)
    
    return combined_sentiment