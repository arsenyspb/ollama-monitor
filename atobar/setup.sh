#!/bin/bash
set -e

echo "Setting up ollama-monitor environment..."

# Setup virtual environment using uv
uv venv .venv
source .venv/bin/activate

# Install Python dependencies
uv pip install pytest plotext==5.2.8
echo "Environment setup complete."