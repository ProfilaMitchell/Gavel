# Use an official Python runtime as a parent image
# Using python:3.11 or 3.12 slim version is often a good balance
FROM python:3.12.9

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE 1 # Prevents python creating .pyc files
ENV PYTHONUNBUFFERED 1       # Prevents python buffering stdout/stderr

# Set the working directory in the container
WORKDIR /app

# Install system dependencies if needed (unlikely for this app, but example shown)
# RUN apt-get update && apt-get install -y --no-install-recommends some-package && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
# We copy this first to leverage Docker cache - dependencies only reinstall if requirements.txt changes
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
# Assuming your code (main.py, crew.py, templates/, static/, etc.) is inside a 'src' directory
# If not, adjust the source path (e.g., COPY . . if main.py is in the root)
COPY ./cardano_governance /app/cardano_governance

# Also copy govtools_api.py if it's outside src but needed
# COPY ./tools/govtools_api.py /app/tools/govtools_api.py # Example if tools is separate


WORKDIR /app/cardano_governance/src

# Make port 8000 available to the world outside this container
# Digital Ocean App Platform typically expects port 8000 or 8080
EXPOSE 8000

# Define the command to run your application
# Use uvicorn to run the FastAPI app located at src.main:app
# --host 0.0.0.0 makes it accessible from outside the container
# --port 8000 matches the EXPOSE directive
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]