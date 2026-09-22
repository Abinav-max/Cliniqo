#!/usr/bin/env bash
# Render Build Script for Cliniqo MediKiosk
set -o errexit

echo "=== [1/3] Upgrading pip ==="
python -m pip install --upgrade pip

echo "=== [2/3] Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== [3/3] Preparing storage directories ==="
mkdir -p data/documents static

echo "=== Build Complete ==="
