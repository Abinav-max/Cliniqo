#!/usr/bin/env bash
# Render Start Script for Cliniqo MediKiosk
set -o errexit

PORT="${PORT:-8000}"
echo "=== Launching Cliniqo MediKiosk on 0.0.0.0:${PORT} ==="

exec uvicorn api.main:app --host 0.0.0.0 --port "$PORT"
