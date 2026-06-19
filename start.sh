#!/usr/bin/env bash
set -e

echo "Training Rasa model..."
cd /app/rasa_bot
rasa train --force

echo "Starting Rasa action server..."
rasa run actions --port 5055 --debug &

echo "Starting Rasa REST server..."
rasa run --enable-api --cors "*" --port 5005 &

echo "Starting Streamlit frontend on port 7860..."
cd /app
streamlit run frontend/app.py \
  --server.port 7860 \
  --server.address 0.0.0.0 \
  --server.enableCORS false \
  --server.enableXsrfProtection false
