import os
import argparse
import uvicorn
from dotenv import load_dotenv
from crew_definition import run_governance_analysis, data_store
from api_server import app

# Load environment variables
load_dotenv()

def run_analysis():
    """Run governance analysis using the CrewAI agents"""
    print("Running Cardano governance analysis...")
    result = run_governance_analysis()
    print("Analysis complete!")
    print(result)
    return result

def start_server(host="0.0.0.0", port=8000, reload=False):
    """Start the API server"""
    # Import web_interface module to ensure templates are created
    import web_interface
    
    print(f"Starting Cardano Governance API server on http://{host}:{port}")
    print(f"Web interface available at http://{host}:{port}/web")
    print(f"API documentation available at http://{host}:{port}/web/api")
    print("Press Ctrl+C to stop the server")
    
    # Make sure we have data
    if not data_store.get_proposals():
        print("No governance data found. Running initial analysis...")
        run_analysis()
    
    # Start the server
    uvicorn.run("api_server:app", host=host, port=port, reload=reload)

def register_agent():
    """Register the agent with Masumi Network"""
    from register_agent import register_agent as reg_agent
    reg_agent()

def update_agent():
    """Update the agent registration with Masumi Network"""
    from register_agent import update_agent as update_agent_func
    update_agent_func()

def setup_environment():
    """Set up the environment variables"""
    # Check if .env file exists
    if not os.path.exists(".env"):
        print("Creating .env file...")
        
        # Create .env file from template
        if os.path.exists(".env.template"):
            with open(".env.template", "r") as template_file:
                template_content = template_file.read()
            
            with open(".env", "w") as env_file:
                env_file.write(template_content)
            
            print(".env file created from template.")
            print("Please edit the .env file to add your API keys and configuration.")
        else:
            # Create empty .env file with minimum required variables
            with open(".env", "w") as env_file:
                env_file.write("# OpenAI API Key for agent intelligence\n")
                env_file.write("OPENAI_API_KEY=\n\n")
                env_file.write("# Masumi Network Configuration\n")
                env_file.write("MASUMI_API_KEY=\n")
                env_file.write("MASUMI_PAYMENT_URL=http://localhost:3000/api/payments\n")
                env_file.write("MASUMI_REGISTRY_URL=http://localhost:3001/api/agents\n")
                env_file.write("AGENT_ID=\n\n")
                env_file.write("# Bluesky API Configuration\n")
                env_file.write("BLUESKY_IDENTIFIER=\n")
                env_file.write("BLUESKY_PASSWORD=\n\n")
                env_file.write("# Web Interface Configuration\n")
                env_file.write("WEB_PORT=8000\n")
                env_file.write("API_RATE_LIMIT=100\n")
            
            print(".env file created with basic structure.")
            print("Please edit the .env file to add your API keys and configuration.")
        
        return False
    
    # Check if required environment variables are set
    required_vars = ["OPENAI_API_KEY", "MASUMI_API_KEY"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("The following required environment variables are not set:")
        for var in missing_vars:
            print(f"  - {var}")
        print("Please edit the .env file to add these values.")
        return False
    
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cardano Governance AI Agent")
    
    # Create subparsers for different actions
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")
    
    # Setup subparser
    setup_parser = subparsers.add_parser("setup", help="Set up the environment")
    
    # Analysis subparser
    analysis_parser = subparsers.add_parser("analyze", help="Run governance analysis")
    
    # Server subparser
    server_parser = subparsers.add_parser("serve", help="Start the API server")
    server_parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server to")
    server_parser.add_argument("--port", type=int, default=8000, help="Port to bind the server to")
    server_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    # Register subparser
    register_parser = subparsers.add_parser("register", help="Register agent with Masumi Network")
    
    # Update subparser
    update_parser = subparsers.add_parser("update", help="Update agent registration with Masumi Network")
    
    # Parse arguments
    args = parser.parse_args()
    
    # If no action specified, print help and exit
    if not args.action:
        parser.print_help()
        exit(1)
    
    # Handle actions
    if args.action == "setup":
        setup_environment()
    elif args.action == "analyze":
        if setup_environment():
            run_analysis()
        else:
            print("Environment setup incomplete. Please run 'python3 main.py setup' first.")
    elif args.action == "serve":
        if setup_environment():
            start_server(host=args.host, port=args.port, reload=args.reload)
        else:
            print("Environment setup incomplete. Please run 'python3 main.py setup' first.")
    elif args.action == "register":
        if setup_environment():
            register_agent()
        else:
            print("Environment setup incomplete. Please run 'python3 main.py setup' first.")
    elif args.action == "update":
        if setup_environment():
            update_agent()
        else:
            print("Environment setup incomplete. Please run 'python3 main.py setup' first.")