#!/bin/bash
set -euo pipefail

APP_DIR="/Users/[USERNAME]/Library/Application Support/spotify-dashboard"
mkdir -p "$APP_DIR"

# Wait for the local server to be ready.
for _ in {1..20}; do
  if curl -fsS "http://127.0.0.1:8765/api/refresh/status" >/dev/null 2>&1; then
    break
  fi
  sleep 3
done

# Trigger the actual Spotify refresh.
curl -fsS -X POST "http://127.0.0.1:8765/api/refresh" >/dev/null