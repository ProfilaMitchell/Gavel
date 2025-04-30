from crewai import Agent, Crew, Process, Task
from crewai.tools import tool
from langchain_openai import ChatOpenAI
import os
import datetime
import json
from typing import Dict, List, Any
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .tools.govtools_api import (
    get_proposals,
    get_content_for_proposal,
    get_comments_for_proposal,
)

import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)



# Import your bluesky_integration
from .tools.bluesky_integration import get_proposal_sentiment

# Load environment variables
load_dotenv()

# Initialize LLM
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set.")
llm = ChatOpenAI(model_name="gpt-4-turbo", openai_api_key=openai_api_key)

# --- DataStore Class ---
class DataStore:
    def __init__(self):
        self.proposals = []
        self.social_sentiment = {}
        self.user_sentiment = {}

    def save_proposals(self, proposals: List[Dict[str, Any]]):
        self.proposals = proposals
        return True

    def get_proposals(self) -> List[Dict[str, Any]]:
        return self.proposals
    
    def save_social_sentiment(self, proposal_id: str, sentiment_data: Dict[str, Any]):
        if proposal_id not in self.social_sentiment:
            self.social_sentiment[proposal_id] = []
        self.social_sentiment[proposal_id].append({
            "timestamp": datetime.datetime.now().isoformat(),
            "data": sentiment_data
        })
        return True
    
    def get_social_sentiment(self, proposal_id=None):
        if proposal_id:
            return self.social_sentiment.get(proposal_id, [])
        return self.social_sentiment
    
    def save_user_sentiment(self, proposal_id: str, sentiment: float):
        if proposal_id not in self.user_sentiment:
            self.user_sentiment[proposal_id] = []
        self.user_sentiment[proposal_id].append({
            "timestamp": datetime.datetime.now().isoformat(),
            "sentiment": sentiment
        })
        return True
    
    def get_user_sentiment(self, proposal_id=None):
        if proposal_id:
            return self.user_sentiment.get(proposal_id, [])
        return self.user_sentiment

# Initialize data store
data_store = DataStore()

@tool
def scrape_governance_proposals(limit: int = 1, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Fetch real proposals + full text + comments from the GovTools API.
    Processes only the first proposal for quick testing.
    """
    # 1) Fetch up to `limit` proposals, but we'll only process the very first one.
    proposals = get_proposals(limit=limit, offset=offset)

    results: List[Dict[str, Any]] = []
    for p in proposals[:1]:   # ← only the first proposal
        pid = str(p["id"])

        # 2) Fetch the full-text fields
        content = get_content_for_proposal(pid)
        abstract   = content.get("prop_abstract", "")
        motivation = content.get("prop_motivation", "")
        rationale  = content.get("prop_rationale", "")

        # 3) Fetch the user comments
        comments = get_comments_for_proposal(pid)

        # 4) Combine everything into one record
        record = {
            "id":            pid,
            "title":         p.get("title"),
            "created_at":    p.get("created_at"),
            "updated_at":    p.get("updated_at"),
            # full text:
            "abstract":      abstract,
            "motivation":    motivation,
            "rationale":     rationale,
            # comments for sentiment analysis:
            "comments":      comments,
            # plus any other metadata fields you care about:
            "likes":         p.get("likes"),
            "dislikes":      p.get("dislikes"),
            "comment_count": p.get("comment_count"),
            
            # Add these fields for compatibility with the existing format expected by other agents
            "status":        "Active",
            "category":      content.get("gov_action_type_id", "Unknown"),
            "description":   abstract + "\n\n" + motivation, 
            "date_created":  p.get("created_at"),
            "date_updated":  p.get("updated_at"),
            "url":           f"https://gov.tools/budget_discussion/{pid}"
        }
        results.append(record)

    # Save to the data_store for use by other agents
    data_store.save_proposals(results)
    logger.info(f"Saved {len(results)} proposal(s) to data_store")
    
    # Persist to disk so you can inspect it manually
    path = os.path.join(os.getcwd(), "proposals.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Saved {len(results)} proposal(s) to {path}")

    return results


@tool
def get_proposals_from_datastore() -> List[Dict[str, Any]]:
    """
    Read the most recently scraped proposals from disk and ensure they're in the data_store.
    """
    import json, os
    path = os.path.join(os.getcwd(), "proposals.json")
    if not os.path.exists(path):
        return []
    
    with open(path) as f:
        proposals = json.load(f)
    
    # Sync with in-memory data store
    data_store.save_proposals(proposals)
    logger.info(f"Synchronized {len(proposals)} proposal(s) from disk to data_store")
    
    return proposals


@tool
def analyze_sentiment_for_proposal(proposal_id: str, proposal_title: str, proposal_description: str):
    """
    Analyzes sentiment for a given proposal using comments from gov.tools.
    
    Args:
        proposal_id: The unique identifier of the proposal
        proposal_title: The title of the proposal
        proposal_description: The description of the proposal
    
    Returns:
        A string with the analysis results
    """
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        import statistics
        
        print(f"Analyzing sentiment for proposal {proposal_id}: {proposal_title}")
        
        # Get proposals from data store
        proposals = data_store.get_proposals()
        target_proposal = None
        
        # Find the specific proposal
        for proposal in proposals:
            if proposal["id"] == proposal_id:
                target_proposal = proposal
                break
        
        if not target_proposal:
            return f"Proposal with ID {proposal_id} not found in data store."
        
        # Initialize VADER sentiment analyzer
        analyzer = SentimentIntensityAnalyzer()
        
        # Initialize sentiment storage variables
        all_comments = []
        drep_comments = []
        regular_comments = []
        author_comments = []
        
        # Check if we have processed comments
        if "processed_comments" in target_proposal and target_proposal["processed_comments"]:
            processed_comments = target_proposal["processed_comments"]
            
            # Analyze sentiment with weights
            def calculate_weighted_sentiment(comments_list):
                if not comments_list:
                    return None
                
                total_weighted_score = 0.0
                total_weight = 0.0
                
                for comment in comments_list:
                    # Get the comment text
                    comment_text = comment.get("text", "")
                    
                    # Analyze sentiment if not already present
                    sentiment = analyzer.polarity_scores(comment_text)
                    
                    # Determine weight factors
                    weight = 1.0  # Default weight
                    
                    # Adjust weight based on metadata
                    if comment.get("is_author", False):
                        weight *= 0.5  # Author comments weighted less
                    if comment.get("is_drep", False):
                        weight *= 1.5  # DRep comments weighted more
                    if comment.get("is_thank_you", False):
                        weight *= 0.3  # Thank you messages weighted much less
                        
                    # Length-based weight (longer comments might have more substance)
                    text_length = len(comment_text)
                    length_factor = min(1.0, max(0.5, text_length / 500.0))
                    weight *= length_factor
                    
                    # Store sentiment with comment
                    comment_data = {
                        "text": comment_text,
                        "author": comment.get("author", "Unknown"),
                        "is_drep": comment.get("is_drep", False),
                        "is_author": comment.get("is_author", False),
                        "is_thank_you": comment.get("is_thank_you", False),
                        "date": comment.get("date", "Unknown"),
                        "sentiment": sentiment,
                        "weight": weight
                    }
                    
                    # Apply weight to the sentiment score
                    total_weighted_score += sentiment["compound"] * weight
                    total_weight += weight
                    
                    # Store in appropriate categories
                    all_comments.append(comment_data)
                    
                    if comment.get("is_author", False):
                        author_comments.append(comment_data)
                    elif comment.get("is_drep", False):
                        drep_comments.append(comment_data)
                    else:
                        regular_comments.append(comment_data)
                
                # Calculate weighted average
                if total_weight > 0:
                    return total_weighted_score / total_weight
                return 0.0
            
            # Get weighted sentiment scores for different comment groups
            all_sentiment = calculate_weighted_sentiment(processed_comments["all_comments"])
            community_sentiment = calculate_weighted_sentiment(processed_comments["community_comments"])
            author_sentiment = calculate_weighted_sentiment(processed_comments["author_comments"])
            drep_sentiment = calculate_weighted_sentiment(processed_comments["drep_comments"])
            
        else:
            # Fallback to the original method if processed_comments isn't available
            # Process comments from the original proposal data
            if "comments" in target_proposal and target_proposal["comments"]:
                for comment in target_proposal["comments"]:
                    comment_text = comment.get("text", "")
                    if not comment_text:
                        continue
                    
                    # Analyze sentiment of this comment
                    sentiment = analyzer.polarity_scores(comment_text)
                    
                    # Store with comment metadata
                    comment_data = {
                        "text": comment_text,
                        "author": comment.get("author", "Unknown"),
                        "is_drep": comment.get("is_drep", False),
                        "date": comment.get("date", "Unknown"),
                        "sentiment": sentiment
                    }
                    
                    all_comments.append(comment_data)
                    
                    # Separate DRep and regular comments
                    if comment.get("is_drep", False):
                        drep_comments.append(comment_data)
                    else:
                        regular_comments.append(comment_data)
            
            # Calculate simple aggregate sentiment scores (unweighted)
            def calculate_aggregate(comments):
                if not comments:
                    return None
                
                compound_scores = [c["sentiment"]["compound"] for c in comments]
                pos_scores = [c["sentiment"]["pos"] for c in comments]
                neg_scores = [c["sentiment"]["neg"] for c in comments]
                neu_scores = [c["sentiment"]["neu"] for c in comments]
                
                return {
                    "compound": statistics.mean(compound_scores) if compound_scores else 0,
                    "positive": statistics.mean(pos_scores) if pos_scores else 0,
                    "negative": statistics.mean(neg_scores) if neg_scores else 0,
                    "neutral": statistics.mean(neu_scores) if neu_scores else 0,
                    "sample_size": len(comments)
                }
            
            # Get aggregate scores
            all_sentiment_data = calculate_aggregate(all_comments)
            all_sentiment = all_sentiment_data["compound"] if all_sentiment_data else 0
            drep_sentiment_data = calculate_aggregate(drep_comments)
            drep_sentiment = drep_sentiment_data["compound"] if drep_sentiment_data else 0
            regular_sentiment_data = calculate_aggregate(regular_comments)
            community_sentiment = regular_sentiment_data["compound"] if regular_sentiment_data else 0
            author_sentiment = 0  # No author data in the old method
        
        # Extract keywords (simplified)
        keywords = []
        keywords.append(target_proposal.get("category", "").lower())
        
        # Create the sentiment data structure
        sentiment_data = {
            "compound": all_sentiment,
            "community_sentiment": community_sentiment,
            "author_sentiment": author_sentiment,
            "drep_sentiment": drep_sentiment,
            "positive": sum([c["sentiment"]["pos"] for c in all_comments]) / len(all_comments) if all_comments else 0,
            "negative": sum([c["sentiment"]["neg"] for c in all_comments]) / len(all_comments) if all_comments else 0,
            "neutral": sum([c["sentiment"]["neu"] for c in all_comments]) / len(all_comments) if all_comments else 0,
            "sample_size": len(all_comments),
            "keywords": keywords,
            "sources": {
                "govtools": {
                    "compound": all_sentiment,
                    "comment_count": len(all_comments),
                    "drep_sentiment": drep_sentiment,
                    "drep_count": len(drep_comments),
                    "author_sentiment": author_sentiment,
                    "author_count": len(author_comments),
                    "community_sentiment": community_sentiment,
                    "community_count": len(regular_comments),
                    "comments": all_comments
                },
                "bluesky": {
                    "compound": 0,  # Will be populated when we implement Bluesky integration
                    "post_count": 0,
                    "posts": []
                }
            },
            "total_sources": len(all_comments)
        }
        
        # Save to data store
        data_store.save_social_sentiment(proposal_id, sentiment_data)
        
        # Return a summary
        sentiment_summary = f"""Successfully analyzed sentiment for proposal {proposal_id}.
        
        Overall Sentiment: {sentiment_data['compound']:.2f} (scale: -1 to +1)
        Sample Size: {sentiment_data['sample_size']} comments
        
        Breakdown:
        - GovTools Comments: {len(all_comments)} ({sentiment_data['sources']['govtools']['compound']:.2f})
          - Author Comments: {len(author_comments)} ({0.0 if not author_sentiment else author_sentiment:.2f})
          - DRep Comments: {len(drep_comments)} ({0.0 if not drep_sentiment else drep_sentiment['compound']:.2f})
          - Community Comments: {len(regular_comments)} ({0.0 if not community_sentiment else community_sentiment:.2f})
        
        Raw Data: {json.dumps(sentiment_data, indent=2)}
        """
        
        return sentiment_summary
    except Exception as e:
        error_msg = f"Error analyzing sentiment for proposal {proposal_id}: {str(e)}"
        print(error_msg)
        
        # Create fallback mock data
        sentiment_data = {
            "positive": 0.65,
            "negative": 0.15,
            "neutral": 0.20,
            "compound": 0.5,
            "sample_size": 5,
            "keywords": ["governance", "transparency", "voting"]
        }
        data_store.save_social_sentiment(proposal_id, sentiment_data)
        
        return f"Error during sentiment analysis, created fallback data: {error_msg}"


@tool
def get_user_sentiment(proposal_id: str):
    """
    Gets user sentiment for a given proposal.
    
    Args:
        proposal_id: The unique identifier of the proposal
    
    Returns:
        A string with the user sentiment data
    """
    try:
        user_sentiment_data = data_store.get_user_sentiment(proposal_id)
        if not user_sentiment_data:
            # Mock some user sentiment data
            mock_sentiment = 0.72
            data_store.save_user_sentiment(proposal_id, mock_sentiment)
            return f"No user sentiment found for proposal ID {proposal_id}. Generated mock data with sentiment score: {mock_sentiment}"
        return f"Retrieved user sentiment data for proposal {proposal_id}: {json.dumps(user_sentiment_data)}"
    except Exception as e:
        return f"Error retrieving user sentiment for proposal {proposal_id}: {str(e)}"

@tool
def aggregate_proposal_data():
    """Aggregates proposal data with sentiment analysis"""
    try:
        proposals = data_store.get_proposals()
        social_sentiment = data_store.get_social_sentiment()
        user_sentiment = data_store.get_user_sentiment()

        if not proposals:
            return "No proposals found in data store to aggregate."

        aggregated_data = []

        for proposal in proposals:
            proposal_id = proposal.get("id", "N/A")

            latest_social_sentiment = None
            proposal_social_sentiments = social_sentiment.get(proposal_id, [])
            if proposal_social_sentiments:
                latest_social_sentiment = proposal_social_sentiments[-1].get("data")

            avg_user_sentiment = None
            proposal_user_sentiments = user_sentiment.get(proposal_id, [])
            count = len(proposal_user_sentiments)
            if count > 0:
                sentiments = [item.get("sentiment", 0) for item in proposal_user_sentiments if isinstance(item.get("sentiment"), (int, float))]
                if sentiments:
                    avg_user_sentiment = sum(sentiments) / len(sentiments)

            aggregated_proposal = {
                **proposal,
                "social_sentiment": latest_social_sentiment,
                "user_sentiment": {"average": avg_user_sentiment, "count": count}
            }

            aggregated_data.append(aggregated_proposal)

        return f"Successfully aggregated data for {len(aggregated_data)} proposals. Data: {json.dumps(aggregated_data, indent=2)}"
    except Exception as e:
        return f"Error aggregating proposal data: {str(e)}"

@tool
def analyze_text_sentiment(text: str):
    """
    Analyzes sentiment of arbitrary text.
    
    Args:
        text: The text to analyze
    
    Returns:
        A dictionary with sentiment analysis results
    """
    try:
        sentiment_analyzer = SentimentIntensityAnalyzer()
        sentiment_scores = sentiment_analyzer.polarity_scores(text)
        return {
            "status": "success",
            "message": "Successfully analyzed text sentiment",
            "data": {
                "positive": sentiment_scores["pos"],
                "negative": sentiment_scores["neg"],
                "neutral": sentiment_scores["neu"],
                "compound": sentiment_scores["compound"]
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error analyzing text sentiment: {str(e)}"
        }

class CardanoGovernance:
    """Crew for analyzing Cardano governance proposals and sentiment"""
    
    def proposal_scraper(self):
        """Agent for scraping governance proposals"""
        return Agent(
            role="Proposal Scraper",
            goal="Scrape and collect governance proposals from specified sources",
            backstory="An expert in data collection and web scraping, focused on gathering the latest Cardano governance proposals.",
            verbose=True,
            llm=llm,
            tools=[scrape_governance_proposals, get_proposals_from_datastore]
        )
    
    def sentiment_analyzer(self):
        """Agent for analyzing sentiment from various sources"""
        return Agent(
            role="Sentiment Analyzer",
            goal="Analyze sentiment from social media and other sources regarding governance proposals",
            backstory="A data scientist specialized in sentiment analysis and social media trends in the blockchain space.",
            verbose=True,
            llm=llm,
            tools=[analyze_sentiment_for_proposal, get_user_sentiment, get_proposals_from_datastore]
        )
    
    def data_aggregator(self):
        """Agent for aggregating proposal data with sentiment analysis"""
        return Agent(
            role="Data Aggregator",
            goal="Combine proposal data with sentiment analysis to provide comprehensive insights",
            backstory="An analytics expert who specializes in synthesizing complex data into actionable insights for governance decisions.",
            verbose=True,
            llm=llm,
            tools=[aggregate_proposal_data, get_proposals_from_datastore]
        )
    
    def scrape_proposals_task(self):
        """Task for scraping governance proposals"""
        return Task(
            description="""
            Scrape the latest governance proposals from gov.tools and other sources.
            Use the scrape_governance_proposals tool to fetch all the proposals.
            Ensure you return a JSON with all proposal details (IDs, titles, descriptions, etc.)
            """,
            expected_output="A comprehensive JSON of current governance proposals with their complete details",
            agent=self.proposal_scraper()
        )
    
    def analyze_sentiment_task(self):
        """Task for analyzing sentiment for each proposal"""
        return Task(
            description="""
            Analyze sentiment for each governance proposal using social media and community sources.
            
            IMPORTANT: First, use the get_proposals_from_datastore tool to retrieve all the proposals that were scraped in the previous task.
            The proposals are stored as JSON objects with these fields: id, title, description, status, category, url, date_created, date_updated.
            
            For EACH proposal in the JSON array:
            1. Extract the proposal_id, proposal_title, and proposal_description
            2. Call analyze_sentiment_for_proposal with these exact parameters
            3. Then call get_user_sentiment with the proposal_id
            
            Provide a summary of sentiment analysis for each proposal, including any insights that can be derived from the sentiment data.
            """,
            expected_output="A complete sentiment analysis report for each proposal, including social sentiment and user sentiment data",
            agent=self.sentiment_analyzer(),
            context=[self.scrape_proposals_task()]
        )
    
    def aggregate_insights_task(self):
        """Task for aggregating proposal data with sentiment analysis"""
        return Task(
            description="""
            Aggregate all proposal data with sentiment analysis to provide comprehensive insights.
            
            1. Call the aggregate_proposal_data tool to combine all proposal data with sentiment analysis
            2. Review the aggregated data to identify patterns, trends, or notable insights
            3. Provide actionable recommendations based on the sentiment analysis across all proposals
            
            Your final report should include:
            - Summary of each proposal with its sentiment analysis
            - Overall community sentiment trends
            - Key insights that would be valuable for governance decision-makers
            - Actionable recommendations based on the sentiment analysis
            """,
            expected_output="A comprehensive report on proposals with integrated sentiment analysis and actionable insights",
            agent=self.data_aggregator(),
            context=[self.scrape_proposals_task(), self.analyze_sentiment_task()]
        )
    
    def crew(self):
        """Creates the Cardano Governance crew"""
        return Crew(
            agents=[
                self.proposal_scraper(),
                self.sentiment_analyzer(),
                self.data_aggregator()
            ],
            tasks=[
                self.scrape_proposals_task(),
                self.analyze_sentiment_task(),
                self.aggregate_insights_task()
            ],
            process=Process.sequential,
            verbose=True
        )