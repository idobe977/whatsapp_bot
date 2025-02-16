FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY project/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY project/ ./project/
COPY surveys/ ./surveys/

# Set environment variables
ENV PYTHONPATH=/app
ENV PORT=8000

# Create necessary directories
RUN mkdir -p surveys

# Run the application
CMD ["uvicorn", "project.main:app", "--host", "0.0.0.0", "--port", "8000"] 