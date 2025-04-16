#!/bin/bash

# Script to activate the Python virtual environment and start the FastAPI backend server.

VENV_ACTIVATE=".venv/bin/activate"
FALLBACK_VENV_ACTIVATE="venv/bin/activate"

# Activate virtual environment
if [ -f "$VENV_ACTIVATE" ]; then
    echo "Activating virtual environment: .venv"
    source "$VENV_ACTIVATE"
elif [ -f "$FALLBACK_VENV_ACTIVATE" ]; then
    echo "Activating virtual environment: venv"
    source "$FALLBACK_VENV_ACTIVATE"
else
    echo "Error: Activation script not found at .venv/bin/activate or venv/bin/activate." >&2
    exit 1
fi

# Check if VIRTUAL_ENV is set
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Error: VIRTUAL_ENV not set after sourcing activate script." >&2
    exit 1
fi

PYTHON_EXEC="$VIRTUAL_ENV/bin/python"

if [ ! -x "$PYTHON_EXEC" ]; then
    echo "Error: Python executable not found or not executable at $PYTHON_EXEC" >&2
    exit 1
fi

# Check for necessary API keys (optional but recommended)
if [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "Warning: OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable is not set." >&2
    echo "The Controller Agent might fail if it requires one of these keys." >&2
fi

HOST=${API_HOST:-"127.0.0.1"}
PORT=${API_PORT:-8000}

echo "Changing directory to backend..."
cd backend || exit 1 # Change directory and exit if it fails

echo "Starting FastAPI backend server using $PYTHON_EXEC on http://${HOST}:${PORT}..."

# Run uvicorn as a module using the virtual environment's Python executable
# Use exec to replace the script process with the Python process running uvicorn
exec "$PYTHON_EXEC" -m uvicorn api_server:app --host "${HOST}" --port "${PORT}" --reload
