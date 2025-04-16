#!/bin/bash

# Script to navigate to the frontend directory and start the Vite development server.

FRONTEND_DIR="frontend"

if [ ! -d "$FRONTEND_DIR" ]; then
    echo "Error: Frontend directory '$FRONTEND_DIR' not found." >&2
    exit 1
fi

if [ ! -f "$FRONTEND_DIR/package.json" ]; then
    echo "Error: package.json not found in '$FRONTEND_DIR'. Have you run 'npm install' (or yarn/pnpm)?" >&2
    exit 1
fi

cd "$FRONTEND_DIR" || exit 1

echo "Starting Vite frontend development server (usually on http://localhost:5173)..."

# Use exec to replace the script process with the npm process
# Adjust 'npm run dev' if you use yarn ('yarn dev') or pnpm ('pnpm dev')
exec npm run dev
