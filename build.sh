#!/usr/bin/env bash
set -e

echo "Installing backend dependencies..."
cd backend
pip install -r requirements.txt
cd ..

echo "Building frontend..."
cd frontend
npm install
npm run build
cd ..

echo "Copying frontend build to backend static..."
rm -rf backend/static
mkdir -p backend/static

# If using Vite:
if [ -d "frontend/dist" ]; then
  cp -r frontend/dist/* backend/static/
fi

# If using CRA:
if [ -d "frontend/build" ]; then
  cp -r frontend/build/* backend/static/
fi

echo "Build complete."
