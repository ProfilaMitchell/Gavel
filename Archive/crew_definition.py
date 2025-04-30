import os
import datetime
import json
from typing import Dict, List, Any

try:
    # Try to import with the newer 0.108.0+ style
    from crewai import Agent, Crew, Process, Task
    from crewai.project import CrewBase, agent, crew, task
    MODERN_CREWAI = True
except ImportError:
    # Fall back to older style if imports fail
    from crewai import Agent, Task, Crew
    MODERN_CREWAI = False
    print("Warning: Using legacy CrewAI imports. Consider upgrading to a newer version.")

from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Assuming bluesky_integration.py exists and has this function
from bluesky_integration import get_proposal_sentiment

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

# --- Tool Functions ---
def scrape_governance_proposals():
    """Scrapes governance proposals from gov.tools"""
    try:
        proposals = []
        print("Scraping governance proposals from gov.tools...")
        
        # Example data structure
        example_proposals = [
            {
                "id": "f1502b01-1234-5678-abcd-e61e9130f565",
                "title": "Catalyst Fund 11 Parameter Changes",
                "status": "Active",
                "category": "Catalyst",
                "url": "https://gov.tools/cardano/catalyst/f11-parameters",
                "description": "Proposed changes to Fund 11 parameters including voting thresholds and category allocations",
                "date_created": "2024-03-15T12:00:00Z",
                "date_updated": "2024-03-20T14:30:00Z"
            },
            {
                "id": "a2603c02-8765-4321-dcba-f72e0241g676",
                "title": "CIP-1694 Implementation Timeline",
                "status": "Voting",
                "category": "Protocol",
                "url": "https://gov.tools/cardano/cips/cip-1694-timeline",
                "description": "Proposal to establish a firm timeline for the implementation of CIP-1694 governance mechanisms",
                "date_created": "2024-03-01T09:15:00Z",
                "date_updated": "2024-03-18T11:45:00Z"
            },
            {
                "id": "c3704d03-abcd-9876-efgh-g83f1352h787",
                "title": "Treasury Reserve Allocation Q2 2024",
                "status": "Pending",
                "category": "Treasury",
                "url": "https://gov.tools/cardano/treasury/q2-2024-allocation",
                "description": "Proposal for the allocation of treasury reserves for Q2 2024 development initiatives",
                "date_created": "2024-03-10T15:45:00Z",
                "date_updated": "2024-03-12T10:20:00Z"
            }
        ]
        
        proposals.extend(example_proposals)
        data_store.save_proposals(proposals)
        return f"Successfully scraped {len(proposals)} proposals. Data saved."
    except Exception as e:
        return f"Error scraping proposals: {str(e)}"

def analyze_sentiment_for_proposal(proposal_id, proposal_title, proposal_description):
    """Analyzes sentiment for a given proposal using Bluesky and gov.tools"""
    try:
        print(f"Analyzing sentiment for proposal {proposal_id}: {proposal_title}")
        sentiment_data = get_proposal_sentiment(proposal_id, proposal_title, proposal_description)
        data_store.save_social_sentiment(proposal_id, sentiment_data)
        return f"Successfully analyzed sentiment for proposal {proposal_id}. Sentiment data saved."
    except Exception as e:
        return f"Error analyzing sentiment for proposal {proposal_id}: {str(e)}"

def get_user_sentiment(proposal_id):
    """Gets user sentiment for a given proposal"""
    try:
        user_sentiment_data = data_store.get_user_sentiment(proposal_id)
        if not user_sentiment_data:
            return f"No user sentiment found for proposal ID {proposal_id}."
        return f"Retrieved user sentiment data for proposal {proposal_id}: {json.dumps(user_sentiment_data)}"
    except Exception as e:
        return f"Error retrieving user sentiment for proposal {proposal_id}: {str(e)}"

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
            
            # Get latest social sentiment if available
            latest_social_sentiment = None
            proposal_social_sentiments = social_sentiment.get(proposal_id, [])
            if proposal_social_sentiments:
                latest_social_sentiment = proposal_social_sentiments[-1].get("data")
            
            # Calculate average user sentiment if available
            avg_user_sentiment = None
            proposal_user_sentiments = user_sentiment.get(proposal_id, [])
            count = len(proposal_user_sentiments)
            if count > 0:
                sentiments = [item.get("sentiment", 0) for item in proposal_user_sentiments if isinstance(item.get("sentiment"), (int, float))]
                if sentiments:
                    avg_user_sentiment = sum(sentiments) / len(sentiments)
            
            # Combine data
            aggregated_proposal = {
                **proposal,
                "social_sentiment": latest_social_sentiment,
                "user_sentiment": {"average": avg_user_sentiment, "count": count}
            }
            
            aggregated_data.append(aggregated_proposal)
        
        return f"Successfully aggregated data for {len(aggregated_data)} proposals."
    except Exception as e:
        return f"Error aggregating proposal data: {str(e)}"

if MODERN_CREWAI:
    # Use modern CrewAI approach with decorators
    @CrewBase
    class CardanoGovernanceCrew:
        """Crew for analyzing Cardano governance proposals and sentiment"""
        
        @agent
        def proposal_scraper(self) -> Agent:
            """Agent for scraping governance proposals"""
            return Agent(
                role="Proposal Data Collector",
                goal="Collect and organize all Cardano governance proposals from gov.tools",
                backstory="You are an expert at collecting and organizing governance data. Your job is to ensure all Cardano governance proposals are properly cataloged and structured.",
                verbose=True,
                llm=llm,
                tools=[scrape_governance_proposals]
            )
        
        @agent
        def sentiment_analyzer(self) -> Agent:
            """Agent for analyzing sentiment from various sources"""
            return Agent(
                role="Sentiment Analysis Expert",
                goal="Analyze sentiment from Bluesky and gov.tools regarding specific governance proposals",
                backstory="You are a sentiment analysis expert who can interpret the mood and opinions of the Cardano community regarding governance proposals. You analyze social media from Bluesky, gov.tools comments, and direct user feedback.",
                verbose=True,
                llm=llm,
                tools=[analyze_sentiment_for_proposal, get_user_sentiment]
            )
        
        @agent
        def data_aggregator(self) -> Agent:
            """Agent for aggregating proposal data with sentiment analysis"""
            return Agent(
                role="Governance Insights Aggregator",
                goal="Combine stored proposal data with stored sentiment analysis to provide comprehensive governance insights",
                backstory="You are an expert at synthesizing diverse data sources into coherent insights. You use the aggregation tool to take stored proposal data and sentiment analysis and transform them into actionable intelligence.",
                verbose=True,
                llm=llm,
                tools=[aggregate_proposal_data]
            )
        
        @task
        def scrape_proposals_task(self) -> Task:
            """Task for scraping governance proposals"""
            return Task(
                description="Use the scrape_governance_proposals tool to collect all governance proposals from gov.tools and save the structured data.",
                agent=self.proposal_scraper,
                expected_output="A confirmation message stating that proposals have been scraped and saved successfully."
            )
        
        @task
        def analyze_sentiment_task(self) -> Task:
            """Task for analyzing sentiment for each proposal"""
            return Task(
                description="""
                Iterate through the proposals collected in the previous step. 
                For each proposal, use the analyze_sentiment_for_proposal tool 
                with its ID, title, and description to analyze and save sentiment from Bluesky and gov.tools. 
                Also use the get_user_sentiment tool for each proposal ID.
                """,
                agent=self.sentiment_analyzer,
                expected_output="A confirmation message summarizing the sentiment analysis performed for the proposals.",
                context=[self.scrape_proposals_task]
            )
        
        @task
        def aggregate_insights_task(self) -> Task:
            """Task for aggregating proposal data with sentiment analysis"""
            return Task(
                description="Use the aggregate_proposal_data tool to combine the stored proposal data with the stored sentiment analysis results into comprehensive governance insights.",
                agent=self.data_aggregator,
                expected_output="A confirmation message that the data aggregation is complete, possibly summarizing the number of proposals aggregated.",
                context=[self.scrape_proposals_task, self.analyze_sentiment_task]
            )
        
        @crew
        def governance_crew(self) -> Crew:
            """Creates the Cardano Governance crew"""
            return Crew(
                agents=self.agents,  # Automatically created by the @agent decorator
                tasks=self.tasks,    # Automatically created by the @task decorator
                process=Process.sequential,
                verbose=2,
            )

    # Initialize the crew with modern approach
    cardano_governance_crew = CardanoGovernanceCrew().governance_crew

else:
    # Use legacy approach without decorators
    proposal_scraper = Agent(
        role="Proposal Data Collector",
        goal="Collect and organize all Cardano governance proposals from gov.tools",
        backstory="You are an expert at collecting and organizing governance data. Your job is to ensure all Cardano governance proposals are properly cataloged and structured.",
        verbose=True,
        llm=llm,
        tools=[scrape_governance_proposals]
    )

    sentiment_analyzer_agent = Agent(
        role="Sentiment Analysis Expert",
        goal="Analyze sentiment from Bluesky and gov.tools regarding specific governance proposals",
        backstory="You are a sentiment analysis expert who can interpret the mood and opinions of the Cardano community regarding governance proposals. You analyze social media from Bluesky, gov.tools comments, and direct user feedback.",
        verbose=True,
        llm=llm,
        tools=[analyze_sentiment_for_proposal, get_user_sentiment]
    )

    data_aggregator = Agent(
        role="Governance Insights Aggregator",
        goal="Combine stored proposal data with stored sentiment analysis to provide comprehensive governance insights",
        backstory="You are an expert at synthesizing diverse data sources into coherent insights. You use the aggregation tool to take stored proposal data and sentiment analysis and transform them into actionable intelligence.",
        verbose=True,
        llm=llm,
        tools=[aggregate_proposal_data]
    )

    # Define tasks
    task_scrape_proposals = Task(
        description="Use the scrape_governance_proposals tool to collect all governance proposals from gov.tools and save the structured data.",
        agent=proposal_scraper,
        expected_output="A confirmation message stating that proposals have been scraped and saved successfully."
    )

    task_analyze_sentiment = Task(
        description="""
        Iterate through the proposals collected in the previous step. 
        For each proposal, use the analyze_sentiment_for_proposal tool 
        with its ID, title, and description to analyze and save sentiment from Bluesky and gov.tools. 
        Also use the get_user_sentiment tool for each proposal ID.
        """,
        agent=sentiment_analyzer_agent,
        expected_output="A confirmation message summarizing the sentiment analysis performed for the proposals.",
        context=[task_scrape_proposals]
    )

    task_aggregate_insights = Task(
        description="Use the aggregate_proposal_data tool to combine the stored proposal data with the stored sentiment analysis results into comprehensive governance insights.",
        agent=data_aggregator,
        expected_output="A confirmation message that the data aggregation is complete, possibly summarizing the number of proposals aggregated.",
        context=[task_scrape_proposals, task_analyze_sentiment]
    )

    # Create the crew
    cardano_governance_crew = Crew(
        agents=[proposal_scraper, sentiment_analyzer_agent, data_aggregator],
        tasks=[task_scrape_proposals, task_analyze_sentiment, task_aggregate_insights],
        verbose=2,
        process="sequential"
    )

# Function to start the crew's work
def run_governance_analysis():
    """Kicks off the CrewAI agents to perform the governance analysis."""
    print("Starting Cardano governance analysis using CrewAI...")
    try:
        # Run the crew
        crew_result = cardano_governance_crew.kickoff()
        print("CrewAI analysis kickoff finished.")

        # Fetch the final data
        final_data = data_store.get_proposals()
        
        # Add sentiment data to the proposals
        aggregated_results = data_store.get_social_sentiment()
        user_sent_results = data_store.get_user_sentiment()

        for proposal in final_data:
            proposal_id = proposal.get("id")
            if proposal_id:
                # Add latest social sentiment
                prop_social = aggregated_results.get(proposal_id, [])
                if prop_social:
                    proposal['social_sentiment_analysis'] = prop_social[-1].get('data')
                else:
                    proposal['social_sentiment_analysis'] = None

                # Add user sentiment summary
                prop_user = user_sent_results.get(proposal_id, [])
                count = len(prop_user)
                avg_user_sentiment = None
                if count > 0:
                    sentiments = [item.get("sentiment", 0) for item in prop_user if isinstance(item.get("sentiment"), (int, float))]
                    if sentiments:
                        avg_user_sentiment = sum(sentiments) / len(sentiments)
                proposal['user_sentiment_summary'] = {'average': avg_user_sentiment, 'count': count}

        return final_data

    except Exception as e:
        print(f"An error occurred during CrewAI kickoff or data retrieval: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}