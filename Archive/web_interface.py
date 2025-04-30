from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Dict, Any, List, Optional
import os
import json
from api_server import app as api_app
from crew_definition import data_store, run_governance_analysis

# Create templates directory if it doesn't exist
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)  # Also create static directory

# Initialize templates
templates = Jinja2Templates(directory="templates")

# Mount static files
api_app.mount("/static", StaticFiles(directory="static"), name="static")

# Helper functions
def get_sentiment_color(sentiment_value):
    """Returns a CSS color class based on sentiment value"""
    if sentiment_value is None:
        return "bg-gray-200"
    elif sentiment_value >= 0.5:
        return "bg-green-500"
    elif sentiment_value >= 0.2:
        return "bg-green-300"
    elif sentiment_value >= 0:
        return "bg-green-100"
    elif sentiment_value >= -0.2:
        return "bg-red-100"
    elif sentiment_value >= -0.5:
        return "bg-red-300"
    else:
        return "bg-red-500"

def get_sentiment_label(sentiment_value):
    """Returns a text label based on sentiment value"""
    if sentiment_value is None:
        return "No Data"
    elif sentiment_value >= 0.5:
        return "Very Positive"
    elif sentiment_value >= 0.2:
        return "Positive"
    elif sentiment_value >= 0:
        return "Slightly Positive"
    elif sentiment_value >= -0.2:
        return "Slightly Negative"
    elif sentiment_value >= -0.5:
        return "Negative"
    else:
        return "Very Negative"

# Routes
@api_app.get("/web", response_class=HTMLResponse)
async def web_index(request: Request):
    """Main web interface page"""
    # Ensure we have data
    if not data_store.get_proposals():
        run_governance_analysis()
    
    # Get proposals with sentiment data
    proposals = data_store.get_proposals()
    aggregated_data = []
    
    for proposal in proposals:
        proposal_id = proposal["id"]
        
        # Get latest social sentiment if available
        social_sentiment = None
        social_sentiment_raw = data_store.get_social_sentiment(proposal_id)
        if social_sentiment_raw:
            social_sentiment = social_sentiment_raw[-1]["data"]["compound"]
        
        # Calculate average user sentiment if available
        user_sentiment = None
        user_sentiment_raw = data_store.get_user_sentiment(proposal_id)
        if user_sentiment_raw:
            sentiments = [item["sentiment"] for item in user_sentiment_raw]
            if sentiments:
                user_sentiment = sum(sentiments) / len(sentiments)
        
        # Combine data
        aggregated_proposal = {
            **proposal,
            "social_sentiment": social_sentiment,
            "social_sentiment_color": get_sentiment_color(social_sentiment),
            "social_sentiment_label": get_sentiment_label(social_sentiment),
            "user_sentiment": user_sentiment,
            "user_sentiment_color": get_sentiment_color(user_sentiment),
            "user_sentiment_label": get_sentiment_label(user_sentiment),
            "user_sentiment_count": len(user_sentiment_raw) if user_sentiment_raw else 0
        }
        
        aggregated_data.append(aggregated_proposal)
    
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "proposals": aggregated_data
        }
    )

@api_app.get("/web/proposal/{proposal_id}", response_class=HTMLResponse)
async def web_proposal_detail(request: Request, proposal_id: str):
    """Proposal detail page"""
    # Find the proposal
    proposals = data_store.get_proposals()
    proposal = next((p for p in proposals if p["id"] == proposal_id), None)
    
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    # Get sentiment data
    social_sentiment_raw = data_store.get_social_sentiment(proposal_id)
    user_sentiment_raw = data_store.get_user_sentiment(proposal_id)
    
    # Calculate social sentiment data
    social_sentiment = None
    social_sentiment_history = []
    bluesky_sentiment = None
    govtools_sentiment = None
    bluesky_posts = []
    govtools_comments = []
    
    if social_sentiment_raw:
        latest = social_sentiment_raw[-1]["data"]
        social_sentiment = latest.get("compound", 0)
        
        # Get source-specific sentiment
        sources = latest.get("sources", {})
        bluesky_data = sources.get("bluesky", {})
        govtools_data = sources.get("govtools", {})
        
        bluesky_sentiment = bluesky_data.get("compound", 0)
        govtools_sentiment = govtools_data.get("compound", 0)
        
        # Get posts and comments
        bluesky_posts = bluesky_data.get("posts", [])
        govtools_comments = govtools_data.get("comments", [])
        
        # Create history data for chart
        for entry in social_sentiment_raw:
            social_sentiment_history.append({
                "timestamp": entry["timestamp"],
                "data": entry["data"]
            })
# Calculate user sentiment
    user_sentiment = None
    user_sentiment_history = []
    if user_sentiment_raw:
        sentiments = [item["sentiment"] for item in user_sentiment_raw]
        if sentiments:
            user_sentiment = sum(sentiments) / len(sentiments)
        # Create history data for chart
        for entry in user_sentiment_raw:
            user_sentiment_history.append({
                "timestamp": entry["timestamp"],
                "sentiment": entry["sentiment"]
            })
    
    # Helper function to get counts
    def get_count(sentiment_data, key):
        if not sentiment_data:
            return 0
        return sentiment_data.get(key, 0)
    
    # Combine data
    proposal_data = {
        **proposal,
        "social_sentiment": social_sentiment,
        "social_sentiment_color": get_sentiment_color(social_sentiment),
        "social_sentiment_label": get_sentiment_label(social_sentiment),
        "social_sentiment_history": json.dumps(social_sentiment_history),
        "social_sentiment_count": latest.get("total_sources", 0) if social_sentiment_raw else 0,
        
        "bluesky_sentiment": bluesky_sentiment,
        "bluesky_sentiment_color": get_sentiment_color(bluesky_sentiment),
        "bluesky_sentiment_label": get_sentiment_label(bluesky_sentiment),
        "bluesky_post_count": get_count(bluesky_data, "post_count") if social_sentiment_raw else 0,
        "bluesky_posts": bluesky_posts,
        
        "govtools_sentiment": govtools_sentiment,
        "govtools_sentiment_color": get_sentiment_color(govtools_sentiment),
        "govtools_sentiment_label": get_sentiment_label(govtools_sentiment),
        "govtools_comment_count": get_count(govtools_data, "comment_count") if social_sentiment_raw else 0,
        "govtools_comments": govtools_comments,
        
        "user_sentiment": user_sentiment,
        "user_sentiment_color": get_sentiment_color(user_sentiment),
        "user_sentiment_label": get_sentiment_label(user_sentiment),
        "user_sentiment_history": json.dumps(user_sentiment_history),
        "user_sentiment_count": len(user_sentiment_raw) if user_sentiment_raw else 0
    }
    
    return templates.TemplateResponse(
        "proposal_detail.html", 
        {
            "request": request, 
            "proposal": proposal_data
        }
    )

@api_app.post("/web/proposal/{proposal_id}/sentiment")
async def web_submit_sentiment(request: Request, proposal_id: str, sentiment: float = Form(...)):
    """Submit user sentiment for a proposal"""
    # Validate sentiment value
    if sentiment < -1.0 or sentiment > 1.0:
        raise HTTPException(status_code=400, detail="Sentiment must be between -1.0 and 1.0")
    
    # Find the proposal
    proposals = data_store.get_proposals()
    proposal = next((p for p in proposals if p["id"] == proposal_id), None)
    
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    # Save user sentiment
    data_store.save_user_sentiment(proposal_id, sentiment)
    
    # Redirect back to proposal detail page
    return templates.TemplateResponse(
        "redirect.html", 
        {
            "request": request, 
            "url": f"/web/proposal/{proposal_id}"
        }
    )

@api_app.get("/web/api", response_class=HTMLResponse)
async def web_api_docs(request: Request):
    """API documentation page"""
    return templates.TemplateResponse(
        "api_docs.html", 
        {
            "request": request
        }
    )

# Create HTML templates
def create_templates():
    """Create HTML templates for the web interface"""
    # Create templates directory if it doesn't exist
    os.makedirs("templates", exist_ok=True)
    
    # Index template
    index_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cardano Governance Hub</title>
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    </head>
    <body class="bg-gray-100">
        <header class="bg-blue-900 text-white p-4">
            <div class="container mx-auto">
                <h1 class="text-3xl font-bold">Cardano Governance Hub</h1>
                <p class="text-lg">Community Sentiment Analysis for Cardano Governance</p>
            </div>
        </header>
        
        <nav class="bg-blue-800 text-white p-2">
            <div class="container mx-auto flex">
                <a href="/web" class="px-4 py-2 hover:bg-blue-700">Home</a>
                <a href="/web/api" class="px-4 py-2 hover:bg-blue-700">API Documentation</a>
            </div>
        </nav>
        
        <main class="container mx-auto p-4">
            <div class="bg-white p-6 rounded-lg shadow-md mb-6">
                <h2 class="text-2xl font-bold mb-4">Governance Proposals</h2>
                <p class="mb-6">Browse current Cardano governance proposals and view community sentiment.</p>
                
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {% for proposal in proposals %}
                    <div class="border rounded-lg overflow-hidden shadow-md hover:shadow-lg transition-shadow">
                        <div class="p-4">
                            <div class="flex justify-between items-start">
                                <h3 class="text-xl font-bold">{{ proposal.title }}</h3>
                                <span class="px-2 py-1 text-sm rounded-full bg-{% if proposal.status == 'Active' %}green-500{% elif proposal.status == 'Voting' %}blue-500{% else %}gray-500{% endif %} text-white">{{ proposal.status }}</span>
                            </div>
                            <p class="text-sm text-gray-500 mt-1">{{ proposal.category }}</p>
                            <p class="mt-3 text-gray-700">{{ proposal.description }}</p>
                        </div>
                        
                        <div class="border-t p-4">
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <p class="text-sm font-medium text-gray-700">Social Sentiment</p>
                                    <div class="flex items-center mt-1">
                                        <div class="w-20 h-4 rounded {{ proposal.social_sentiment_color }}"></div>
                                        <span class="ml-2 text-sm">{{ proposal.social_sentiment_label }}</span>
                                    </div>
                                </div>
                                <div>
                                    <p class="text-sm font-medium text-gray-700">User Sentiment</p>
                                    <div class="flex items-center mt-1">
                                        <div class="w-20 h-4 rounded {{ proposal.user_sentiment_color }}"></div>
                                        <span class="ml-2 text-sm">{{ proposal.user_sentiment_label }}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="bg-gray-50 p-4 border-t">
                            <a href="/web/proposal/{{ proposal.id }}" class="inline-block px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">View Details</a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </main>
        
        <footer class="bg-gray-800 text-white p-4">
            <div class="container mx-auto">
                <p>© 2025 Cardano Governance Hub - Powered by Masumi Network</p>
            </div>
        </footer>
    </body>
    </html>
    """
    
    # Create the other templates
    # For brevity, we'll define just the essential templates here
    # In a real implementation, you'd include the complete HTML for all templates
    
    # Proposal detail template (simplified)
    proposal_detail_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{{ proposal.title }} - Cardano Governance Hub</title>
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.min.js"></script>
    </head>
    <body class="bg-gray-100">
        <!-- Header and navigation omitted for brevity -->
        
        <main class="container mx-auto p-4">
            <div class="bg-white p-6 rounded-lg shadow-md mb-6">
                <div class="mb-6">
                    <a href="/web" class="text-blue-600 hover:underline">← Back to Proposals</a>
                </div>
                
                <div class="flex justify-between items-start mb-4">
                    <h2 class="text-2xl font-bold">{{ proposal.title }}</h2>
                    <span class="px-3 py-1 text-sm rounded-full bg-{% if proposal.status == 'Active' %}green-500{% elif proposal.status == 'Voting' %}blue-500{% else %}gray-500{% endif %} text-white">{{ proposal.status }}</span>
                </div>
                
                <!-- Proposal details, sentiment data, and charts would go here -->
                
            </div>
        </main>
        
        <footer class="bg-gray-800 text-white p-4">
            <div class="container mx-auto">
                <p>© 2025 Cardano Governance Hub - Powered by Masumi Network</p>
            </div>
        </footer>
        
        <!-- JavaScript for charts and interactivity would go here -->
    </body>
    </html>
    """
    
    # API docs template (simplified)
    api_docs_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>API Documentation - Cardano Governance Hub</title>
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    </head>
    <body class="bg-gray-100">
        <!-- Header and navigation omitted for brevity -->
        
        <main class="container mx-auto p-4">
            <div class="bg-white p-6 rounded-lg shadow-md mb-6">
                <h2 class="text-2xl font-bold mb-4">API Documentation</h2>
                <!-- API documentation would go here -->
            </div>
        </main>
        
        <footer class="bg-gray-800 text-white p-4">
            <div class="container mx-auto">
                <p>© 2025 Cardano Governance Hub - Powered by Masumi Network</p>
            </div>
        </footer>
    </body>
    </html>
    """
    
    # Redirect template
    redirect_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="0;url={{ url }}">
        <title>Redirecting...</title>
    </head>
    <body>
        <p>Redirecting to <a href="{{ url }}">{{ url }}</a>...</p>
    </body>
    </html>
    """
    
    # Write templates to files
    with open("templates/index.html", "w") as f:
        f.write(index_html)
    
    with open("templates/proposal_detail.html", "w") as f:
        f.write(proposal_detail_html)
    
    with open("templates/api_docs.html", "w") as f:
        f.write(api_docs_html)
    
    with open("templates/redirect.html", "w") as f:
        f.write(redirect_html)

# Create the templates when the module is imported
create_templates()