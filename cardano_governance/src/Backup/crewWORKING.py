# === Imports ===
import os
import datetime
import json
import logging
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Near the top of crew.py
# --- CrewAI Imports ---
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task # Import decorators
# from crewai.tools import tool # <<<--- REMOVE OR COMMENT OUT THIS LINE
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool # <<<--- ADD THIS LINE

# --- Tool Imports ---
# Use relative import now that tools/ is in the same directory (src)
try:
    from tools.govtools_api import ( # <--- Relative import
        get_proposals as api_get_proposals,
        get_content_for_proposal,
        get_comments_for_proposal,
        get_proposal_by_id,
        process_comments_for_sentiment
    )
    # Uncomment if you have this file and need it:
    # from tools.bluesky_integration import get_proposal_sentiment
except ImportError as e:
    raise ImportError(f"Could not import tools using relative path. Ensure tools/govtools_api.py exists in the same directory as crew.py. Error: {e}")


# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Load Environment Variables ---
# Load .env from the current directory (src)
load_dotenv()

# === DataStore Class ===
# Defined outside the CrewBase class as it's used by global tool functions
class DataStore:
    def __init__(self):
        self.proposals: List[Dict[str, Any]] = []
        self.social_sentiment: Dict[str, List[Dict[str, Any]]] = {}
        self.user_sentiment: Dict[str, List[Dict[str, Any]]] = {}
        self.aggregated_data: List[Dict[str, Any]] = []
        logger.info("DataStore initialized.")

    def save_proposals(self, proposals: List[Dict[str, Any]]): self.proposals = proposals; logger.info(f"DS: Saved {len(proposals)} proposals."); return True
    def get_proposals(self) -> List[Dict[str, Any]]: logger.info(f"DS: Retrieving {len(self.proposals)} proposals."); return self.proposals
    def save_social_sentiment(self, proposal_id: str, sentiment_data: Dict[str, Any]):
        if proposal_id not in self.social_sentiment: self.social_sentiment[proposal_id] = []
        self.social_sentiment[proposal_id].append({"timestamp": datetime.datetime.now().isoformat(), "data": sentiment_data})
        logger.info(f"DS: Saved social sentiment for {proposal_id}."); return True
    def get_social_sentiment(self, proposal_id: Optional[str] = None) -> Any:
        if proposal_id: data = self.social_sentiment.get(proposal_id, []); logger.info(f"DS: Retrieved {len(data)} social records for {proposal_id}."); return data
        logger.info(f"DS: Retrieved social sentiment for {len(self.social_sentiment)} proposals."); return self.social_sentiment
    def save_user_sentiment(self, proposal_id: str, sentiment: float):
         if proposal_id not in self.user_sentiment: self.user_sentiment[proposal_id] = []
         self.user_sentiment[proposal_id].append({"timestamp": datetime.datetime.now().isoformat(), "sentiment": sentiment})
         logger.info(f"DS: Saved user sentiment {sentiment} for {proposal_id}."); return True
    def get_user_sentiment(self, proposal_id: Optional[str] = None) -> Any:
        if proposal_id: data = self.user_sentiment.get(proposal_id, []); logger.info(f"DS: Retrieved {len(data)} user records for {proposal_id}."); return data
        logger.info(f"DS: Retrieved user sentiment for {len(self.user_sentiment)} proposals."); return self.user_sentiment
    def save_aggregated_data(self, data: List[Dict[str, Any]]): self.aggregated_data = data; logger.info(f"DS: Saved aggregated data for {len(data)} proposals."); return True
    def get_aggregated_data(self) -> List[Dict[str, Any]]: logger.info(f"DS: Retrieved aggregated data for {len(self.aggregated_data)} proposals."); return self.aggregated_data

    # --- Helper methods for disk persistence (ADDED BACK) ---
    def _save_to_disk(self, filename: str, data: Any):
        """Saves data to a JSON file relative to this script's location."""
        try:
            # Get the directory where crew.py is located
            script_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(script_dir, filename)
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str) # Use default=str for datetime etc.
            logger.info(f"DS: Saved data to {path}")
        except Exception as e:
            logger.error(f"DS: Failed to save data to {filename}: {e}") # Log error if saving fails

    def _load_from_disk(self, filename: str) -> Any:
        """Loads data from a JSON file relative to this script's location."""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(script_dir, filename)
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                logger.info(f"DS: Loaded data from {path}")
                return data
            else:
                logger.warning(f"DS: File {filename} not found in {script_dir}, returning default empty data.")
                # Return default types based on filename
                if "sentiment" in filename or "aggregated" in filename:
                    return {} if "sentiment" in filename else []
                return [] # Default for proposals
        except Exception as e:
            logger.error(f"DS: Failed to load data from {filename}: {e}")
            # Return default on error
            return {} if "sentiment" in filename else []

# === Global Instances (Needed by Tools) ===
# Initialize globally so tool functions can access them
# Tools decorated with @tool are essentially standalone functions during definition
data_store = DataStore()
sentiment_analyzer_instance = SentimentIntensityAnalyzer()

# === Tool Definitions ===
# Tools defined globally using the @tool decorator
@tool
def scrape_governance_proposals(limit: int = 1, offset: int = 0) -> str:
    """
    Fetches governance proposals using the GovTools API, ensuring title is fetched,
    processes them, stores them in the DataStore, and saves to proposals.json.
    Returns a status message. Processes only the first 'limit' proposals fetched.
    """
    logger.info(f"Tool: scrape_governance_proposals called with limit={limit}, offset={offset}")
    try:
        # 1. Fetch raw proposals (might not have populated content)
        proposals_raw = api_get_proposals(limit=limit, offset=offset)
        if not proposals_raw: return "No proposals found from the API."
        logger.info(f"Tool: Fetched {len(proposals_raw)} raw proposals from API.")

        results: List[Dict[str, Any]] = []
        for p in proposals_raw[:1]: # Process only first
            pid = str(p.get("id"));
            if not pid: continue
            logger.info(f"Tool: Processing proposal ID: {pid}")

            # 2. Explicitly fetch content to ensure title etc. are present
            content = get_content_for_proposal(pid)
            logger.info(f"Tool: Fetched content for proposal {pid}.")

            # 3. Fetch and process comments
            comments_raw = get_comments_for_proposal(pid)
            logger.info(f"Tool: Fetched {len(comments_raw)} raw comments for proposal {pid}.")
            author_id = p.get("user_id") # Needed for comment processing
            processed_comments_data = process_comments_for_sentiment(comments_raw, author_id)
            logger.info(f"Tool: Processed comments for proposal {pid}.")

            # 4. Combine into one record, using fetched content for title
            record = {
                "id":            pid,
                # Use title from explicitly fetched content, fallback to original API or 'Untitled'
                "title":         content.get("prop_name", p.get("title", "Untitled")),
                "created_at":    p.get("created_at"),
                "updated_at":    p.get("updated_at"),
                "abstract":      content.get("prop_abstract", ""),
                "motivation":    content.get("prop_motivation", ""),
                "rationale":     content.get("prop_rationale", ""),
                "comments_raw":  comments_raw,
                "processed_comments": processed_comments_data,
                "likes":         p.get("likes", 0),
                "dislikes":      p.get("dislikes", 0),
                "comment_count": p.get("comment_count", 0),
                "status":        p.get("status", "Unknown"),
                "category":      content.get("gov_action_type_id", "Unknown"),
                "description":   f"{content.get('prop_abstract', '')}\n\n{content.get('prop_motivation', '')}",
                "date_created":  p.get("created_at"),
                "date_updated":  p.get("updated_at"),
                "url":           p.get("url", f"https://gov.tools/budget_discussion/{pid}")
            }
            results.append(record)

        data_store.save_proposals(results)
        data_store._save_to_disk("proposals.json", results)
        return f"Successfully scraped and processed {len(results)} proposal(s)."
    except Exception as e: logger.error(f"Tool Error: {e}", exc_info=True); return f"Error: {e}"

@tool
def get_proposals_from_datastore() -> List[Dict[str, Any]]:
    """Retrieves the list of proposals currently stored in the DataStore."""
    logger.info("Tool: get_proposals_from_datastore called.")
    return data_store.get_proposals() # Access global instance

@tool
def analyze_sentiment_for_proposal(proposal_id: str) -> str:
    """
    Analyzes sentiment for a specific proposal using its processed comments.
    Stores detailed comment sentiments and returns a summary message.
    """
    logger.info(f"Tool: analyze_sentiment_for_proposal called for ID: {proposal_id}")
    try:
        proposals = data_store.get_proposals()
        target_proposal = next((p for p in proposals if p.get("id") == proposal_id), None)
        if not target_proposal: return f"Proposal ID {proposal_id} not found."
        logger.info(f"Tool: Found proposal '{target_proposal.get('title', 'N/A')}' for sentiment analysis.")

        processed_comments = target_proposal.get("processed_comments")
        if not processed_comments or not isinstance(processed_comments, dict):
            # Fallback logic remains the same
            raw_comments = target_proposal.get("comments_raw")
            if raw_comments and isinstance(raw_comments, list):
                author_id = target_proposal.get("user_id"); processed_comments = process_comments_for_sentiment(raw_comments, author_id)
            else: return f"No comments available for proposal {proposal_id}."

        analyzed_comments_details = [] # Store detailed results here
        weighted_scores = []
        WEIGHTS = {"author": 0.5, "drep": 1.5, "thank_you": 0.3, "length_factor_scale": 500.0}

        for comment in processed_comments.get("all_comments", []):
            text = comment.get("text", "");
            if not text: continue
            sentiment_scores = sentiment_analyzer_instance.polarity_scores(text); compound_score = sentiment_scores["compound"]
            weight = 1.0
            if comment.get("is_author"): weight *= WEIGHTS["author"]
            if comment.get("is_drep"): weight *= WEIGHTS["drep"]
            if comment.get("is_thank_you"): weight *= WEIGHTS["thank_you"]
            length_factor = min(1.2, max(0.8, len(text) / WEIGHTS["length_factor_scale"])); weight *= length_factor
            weighted_scores.append(compound_score * weight)
            # Store individual comment text and its compound score
            analyzed_comments_details.append({
                "text": text,
                "compound_score": compound_score,
                # Add other details if needed, e.g., author, date
                "author": comment.get("author", "Unknown"),
                "date": comment.get("date", "Unknown")
            })

        overall_sentiment_compound = sum(weighted_scores) / len(weighted_scores) if weighted_scores else 0.0
        def calculate_group_average(group_key):
            group_comments = processed_comments.get(group_key, [])
            scores = [sentiment_analyzer_instance.polarity_scores(c.get("text",""))["compound"] for c in group_comments if c.get("text")]
            return sum(scores) / len(scores) if scores else 0.0
        community_sentiment_avg = calculate_group_average("community_comments"); author_sentiment_avg = calculate_group_average("author_comments"); drep_sentiment_avg = calculate_group_average("drep_comments")

        # UPDATED: Include detailed_comments in the result saved to DataStore
        sentiment_result = {
            "proposal_id": proposal_id,
            "overall_weighted_compound": overall_sentiment_compound,
            "average_sentiment": {"community": community_sentiment_avg, "author": author_sentiment_avg, "drep": drep_sentiment_avg,},
            "counts": { "total_analyzed": len(analyzed_comments_details), "author": len(processed_comments.get("author_comments", [])), "community": len(processed_comments.get("community_comments", [])), "drep": len(processed_comments.get("drep_comments", [])), "thank_you": processed_comments.get("thank_you_count", 0), "duplicates_filtered": processed_comments.get("duplicate_count", 0), },
            "detailed_comments": analyzed_comments_details, # Store the list of comments and scores
            "analysis_timestamp": datetime.datetime.now().isoformat(),
        }
        data_store.save_social_sentiment(proposal_id, sentiment_result)
        summary = (f"Sentiment analysis complete for proposal {proposal_id}. Overall: {overall_sentiment_compound:.3f}. Analyzed {len(analyzed_comments_details)} comments.")
        logger.info(f"Tool: {summary}")
        return summary
    except Exception as e: logger.error(f"Tool Error: {e}", exc_info=True); return f"Error: {e}"


@tool
def get_user_sentiment(proposal_id: str) -> str:
    """Retrieves user sentiment data for a specific proposal from the DataStore."""
    logger.info(f"Tool: get_user_sentiment called for ID: {proposal_id}")
    try:
        user_sentiment_data = data_store.get_user_sentiment(proposal_id) # Access global instance
        if not user_sentiment_data:
            logger.warning(f"Tool: No user sentiment found for {proposal_id}. Generating mock data.")
            mock_sentiment = 0.72; data_store.save_user_sentiment(proposal_id, mock_sentiment) # Access global instance
            user_sentiment_data = data_store.get_user_sentiment(proposal_id)
            return f"No user sentiment found for proposal ID {proposal_id}. Mock data: {json.dumps(user_sentiment_data)}"
        sentiments = [item.get("sentiment", 0) for item in user_sentiment_data if isinstance(item.get("sentiment"), (int, float))]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else "N/A"; count = len(user_sentiment_data)
        avg_sentiment_str = f"{avg_sentiment:.3f}" if isinstance(avg_sentiment, (int, float)) else avg_sentiment
        summary = f"Retrieved {count} user sentiment record(s) for proposal {proposal_id}. Average: {avg_sentiment_str}."
        logger.info(f"Tool: {summary}"); return summary
    except Exception as e: logger.error(f"Tool Error: {e}", exc_info=True); return f"Error: {e}"


@tool
def aggregate_proposal_data() -> str:
    """
    Aggregates proposal data with sentiment analysis, including detailed comments.
    Saves the result and RETURNS a detailed string summary.
    """
    logger.info("Tool: aggregate_proposal_data called.")
    try:
        proposals = data_store.get_proposals()
        if not proposals: return "No proposals found to aggregate."

        social_sentiment_all = data_store.get_social_sentiment()
        user_sentiment_all = data_store.get_user_sentiment()
        aggregated_results = []
        summary_lines = ["Aggregated Proposal Data:"] # Start summary

        for proposal in proposals:
            proposal_id = proposal.get("id")
            if not proposal_id: continue

            # --- Perform aggregation ---
            latest_social = None; social_history = social_sentiment_all.get(proposal_id, [])
            if social_history: latest_social = max(social_history, key=lambda x: x.get("timestamp", "")).get("data")
            avg_user = None; user_history = user_sentiment_all.get(proposal_id, [])
            user_sentiments = [item.get("sentiment", 0) for item in user_history if isinstance(item.get("sentiment"), (int, float))]
            user_count = len(user_history)
            if user_sentiments: avg_user = sum(user_sentiments) / len(user_sentiments)
            aggregated_proposal = {**proposal, "analysis": {"social_sentiment": latest_social, "user_sentiment": {"average_score": avg_user, "count": user_count}, "aggregation_timestamp": datetime.datetime.now().isoformat()}}
            aggregated_results.append(aggregated_proposal)

            # --- Build the detailed summary string line ---
            title = proposal.get('title', 'N/A')
            score = latest_social.get('overall_weighted_compound', 'N/A') if latest_social else 'N/A'
            score_str = f"{score:.3f}" if isinstance(score, (int, float)) else score
            summary_lines.append(f"\n--- Proposal ---")
            summary_lines.append(f"Title: {title}")
            summary_lines.append(f"Overall Weighted Sentiment: {score_str}")

            # Add detailed comments if available
            detailed_comments = latest_social.get('detailed_comments', []) if latest_social else []
            if detailed_comments:
                summary_lines.append("Comments Analyzed:")
                for comment_detail in detailed_comments:
                    comment_score = comment_detail.get('compound_score', 'N/A')
                    comment_score_str = f"{comment_score:.3f}" if isinstance(comment_score, (int, float)) else comment_score
                    comment_text = comment_detail.get('text', 'N/A').replace('\n', ' ') # Replace newlines for cleaner summary
                    summary_lines.append(f"- Score: {comment_score_str}, Text: \"{comment_text[:100]}...\"") # Truncate long comments
            else:
                summary_lines.append("No detailed comments found in analysis.")

        data_store.save_aggregated_data(aggregated_results)
        data_store._save_to_disk("aggregated_data.json", aggregated_results)

        # --- Return the detailed summary string ---
        final_summary = "\n".join(summary_lines)
        logger.info(f"Tool: Aggregation complete. Summary generated.")
        return final_summary

    except Exception as e:
        logger.error(f"Tool Error in aggregate_proposal_data: {e}", exc_info=True)
        return f"Error aggregating proposal data: {e}"


@tool
def parse_proposal_summary(summary_string: str) -> List[Dict[str, str]]:
    """
    Parses the simple string summary of proposals and scores provided in the context.
    Input is a multi-line string where each relevant line contains 'Proposal Title: ..., Overall Weighted Sentiment: ...'.
    Returns a list of dictionaries, each containing 'title' and 'score'.
    """
    logger.info(f"Tool: parse_proposal_summary called with input: {summary_string[:100]}...") # Log first 100 chars
    proposals = []
    try:
        lines = summary_string.strip().split('\n')
        for line in lines:
            # Check if the line contains the expected markers
            if "Proposal Title:" in line and "Overall Weighted Sentiment:" in line:
                # Extract title: part after "Proposal Title:" and before ", Overall Weighted Sentiment:"
                title_part = line.split("Proposal Title:")[1].split(", Overall Weighted Sentiment:")[0].strip()
                # Extract score: part after "Overall Weighted Sentiment:"
                score_part = line.split("Overall Weighted Sentiment:")[1].strip()
                # Append the dictionary with the extracted parts
                # CORRECTED: Use score_part instead of undefined score_str
                proposals.append({"title": title_part, "score": score_part})
                logger.info(f"Parsed proposal: Title='{title_part}', Score='{score_part}'")
        if not proposals:
             logger.warning("Tool: No proposal lines found in the summary string.")
        return proposals
    except Exception as e:
        logger.error(f"Tool Error in parse_proposal_summary: {e}", exc_info=True)
        # Return empty list on error to avoid breaking the agent flow
        return []

# === Crew Definition using @CrewBase ===
@CrewBase
class CardanoGovernanceCrew:
    """CardanoGovernanceCrew using CrewBase structure."""
    # Inputs expected by the crew (can be passed via kickoff)
    # These should match the keys in the 'inputs' dict passed to kickoff()
    # and the placeholders used in task descriptions (e.g., {topic})
    inputs: Optional[Dict[str, Any]] = {'topic': 'Default Topic'} # Example default

    def __init__(self):
        # Initialize LLM for the instance
        self.llm = self._initialize_llm()
        # Note: DataStore is initialized globally above

    def _initialize_llm(self):
        openai_api_key = os.getenv("OPENAI_API_KEY")
        openai_model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4-turbo")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set or found in .env file.")
        logger.info(f"Initializing LLM with model: {openai_model_name}")
        # You might want to adjust temperature or other settings
        return ChatOpenAI(model_name=openai_model_name, openai_api_key=openai_api_key, temperature=0.7)

    # --- Agent Definitions using @agent ---
    # The @agent decorator registers these methods
    @agent
    def proposal_scraper(self) -> Agent:
        return Agent(
            # Configuration can be defined directly or loaded (e.g., from self.agents_config if using YAML)
            role="Cardano Proposal Scraper",
            goal="Fetch the latest Cardano governance proposals from the GovTools API, process their basic details, comments, and content.",
            backstory="You are an automated agent expert in interacting with web APIs, specifically the GovTools API for Cardano. Your primary function is to retrieve proposal listings, detailed content, and associated comments accurately and efficiently. You store this information for other agents to analyze.",
            llm=self.llm,
            tools=[scrape_governance_proposals, get_proposals_from_datastore], # Pass tool functions
            verbose=True,
            allow_delegation=False
        )

    @agent
    def sentiment_analyzer(self) -> Agent:
        return Agent(
            role="Governance Sentiment Analyst",
            goal="Analyze the sentiment expressed in comments associated with Cardano governance proposals, considering different user roles (author, DRep, community).",
            backstory="You are a specialist in Natural Language Processing (NLP) with a focus on sentiment analysis in the context of blockchain governance. You use tools to process comments retrieved by the scraper, calculate weighted sentiment scores, and identify overall community feeling towards proposals. You rely on data prepared by the Proposal Scraper.",
            llm=self.llm,
            tools=[analyze_sentiment_for_proposal, get_user_sentiment, get_proposals_from_datastore],
            verbose=True,
            allow_delegation=False
        )

    @agent
    def data_aggregator(self) -> Agent:
        # UPDATED: Added reporting responsibility to goal/backstory
        return Agent(
            role="Governance Data Synthesizer and Reporter",
            goal=(
                "Combine proposal data with sentiment analysis, then generate a clear, "
                "concise, and insightful report summarizing the findings."
            ),
            backstory=(
                "You are an expert in data integration and analysis. Your role is to take the outputs "
                "from the scraping and sentiment analysis agents, merge them logically using your tool, "
                "and then immediately generate a final human-readable Markdown report based *only* on the aggregated data summary your tool produces. "
                "You focus on accuracy and clarity, using only the provided data."
            ),
            llm=self.llm,
            # Tool needed to get the aggregated summary string
            tools=[aggregate_proposal_data, get_proposals_from_datastore],
            verbose=True,
            allow_delegation=False
        )


    # --- Task Definitions using @task ---
    # The @task decorator registers these methods
    @task
    def scrape_proposals_task(self) -> Task:
        # Task configuration is defined here
        return Task(
            description=(
                "Use the `scrape_governance_proposals` tool to fetch the latest (limit=1 for testing, adjust as needed) "
                "Cardano governance proposals from the GovTools API based on the input `{topic}` (if applicable, otherwise fetch latest). " # Example using input
                "Ensure the tool runs successfully and reports the number of proposals processed."
            ),
            expected_output=(
                "A confirmation message indicating the successful scraping and processing of proposals, "
                "including the number processed. Example: 'Successfully scraped and processed 1 proposal(s).'"
                "The proposal data is now available in the DataStore for subsequent tasks."
            ),
            # Agent assignment uses the method decorated with @agent
            agent=self.proposal_scraper()
            # No context needed for the first task
        )

    @task
    def analyze_sentiment_task(self) -> Task:
        return Task(
            description=(
                "Analyze sentiment for each governance proposal collected in the previous step. "
                "1. Use the `get_proposals_from_datastore` tool to get the list of proposal IDs scraped previously. "
                "2. For *each* proposal ID obtained: "
                "   a. Call the `analyze_sentiment_for_proposal` tool using the proposal ID. "
                "   b. Call the `get_user_sentiment` tool using the proposal ID (to simulate fetching user votes/ratings). "
                "Make sure to execute these steps for all proposals found in the datastore."
            ),
            expected_output=(
                "A series of confirmation messages for each proposal, indicating that both social sentiment analysis "
                "and user sentiment retrieval were attempted. Example for one proposal: "
                "'Sentiment analysis complete for proposal 123... User sentiment retrieved for proposal 123...' "
                "The analysis results are saved in the DataStore."
            ),
            agent=self.sentiment_analyzer(),
            # Context assignment uses the method decorated with @task
            context=[self.scrape_proposals_task()]
        )


    @task
    def aggregate_data_task(self) -> Task:
        # UPDATED: Task now expects detailed summary and asks for comment context
        return Task(
            description=(
                "Consolidate all gathered information and generate the final report. "
                "1. Use the `aggregate_proposal_data` tool once. This tool returns a detailed text summary string including the proposal title, overall score, and a list of individual comments with their scores. "
                "2. Based *only* on the detailed summary string returned by the tool: \n"
                "   - Create a report with the title: '# Cardano Governance Proposal Sentiment Report'.\n"
                "   - State the proposal title and its overall weighted sentiment score.\n"
                "   - List the individual comments and their sentiment scores.\n"
                "   - Summarize key findings: Mention the overall sentiment trend (positive/negative/neutral). Identify any comments with particularly high or low scores. Briefly describe the theme of the most positive and most negative comments to provide context for the overall score.\n"
                "   - Provide a concluding remark based *only* on the sentiment observed for the input topic '{topic}'.\n"
                "Present the final report clearly and concisely in Markdown format. **CRITICAL: Do NOT add any proposals, scores, comments, or findings not present in the tool's output summary string.**"
            ),
            expected_output=(
                "A well-formatted Markdown report containing the title, the actual proposal title/score from the summary string, a list of comments with their scores from the summary string, key findings including comment themes, and a conclusion based only on the provided data."
            ),
            agent=self.data_aggregator(), # Use the updated agent
            context=[self.analyze_sentiment_task()]
        )

    

    # --- Crew Definition using @crew ---
    # The @crew decorator uses the agents and tasks defined above
    @crew
    def crew(self) -> Crew:
        """Creates the CardanoGovernanceCrew"""
        # UPDATED: Removed reporter agent and task
        return Crew(
            agents=[self.proposal_scraper(), self.sentiment_analyzer(), self.data_aggregator()], # Removed reporter
            tasks=[self.scrape_proposals_task(), self.analyze_sentiment_task(), self.aggregate_data_task()], # Removed report task
            process=Process.sequential,
            verbose=True,
        )

# === Example Usage (for local testing, if needed) ===
# This block allows running `python src/crew.py` directly
if __name__ == '__main__':
    print("--- Running CardanoGovernanceCrew Locally (using @CrewBase structure) ---")
    # Define inputs for the run
    crew_inputs = {'topic': 'Catalyst Fund 12 Analysis'}
    try:
        # Instantiate the class
        governance_crew_instance = CardanoGovernanceCrew()
        # Call the @crew decorated method to get the Crew object, then kickoff
        result = governance_crew_instance.crew().kickoff(inputs=crew_inputs)

        print("\n--- Crew Run Result ---")
        print(result)
        print("\n--- Data Files Created (Inspect Manually in src/) ---")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        print(f"- proposals.json (in {script_dir})")
        print(f"- aggregated_data.json (in {script_dir})")
        # if os.path.exists('report.md'): print("- report.md") # If output_file is used

    except ValueError as ve: print(f"\n--- Config Error --- {ve}")
    except ImportError as ie: print(f"\n--- Import Error --- {ie}")
    except Exception as e: print(f"\n--- Unexpected Error --- {e}"); logger.error("Local run failed", exc_info=True)

