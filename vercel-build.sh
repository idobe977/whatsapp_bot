#!/bin/bash

# Install Python dependencies
pip install --no-cache-dir -r project/requirements.txt

# Install frontend dependencies and build
cd project/frontend
npm install
npm run build

# Create necessary directories
mkdir -p ../surveys 
