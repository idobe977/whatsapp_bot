#!/bin/bash

# Install Python dependencies
pip install --no-cache-dir -r project/requirements.txt

# Install frontend dependencies and build
cd project/frontend
npm install
CI=false npm run build
cd ../..

# Create necessary directories
mkdir -p project/surveys 
