# src/cardano_governance/tools/data_store.py
import datetime
from typing import Dict, List, Any

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