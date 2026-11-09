#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "Starting JustMeMedia ContentOS..."
python3 "./app/server.py"
