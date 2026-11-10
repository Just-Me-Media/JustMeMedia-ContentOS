#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "============================================"
echo "  Starting JustMeMedia ContentOS..."
echo "  http://127.0.0.1:8765"
echo "============================================"

OLD_PID=$(lsof -ti :8765 2>/dev/null)
if [ -n "$OLD_PID" ]; then
    echo "  Clearing previous instance (PID: $OLD_PID)..."
    kill -9 $OLD_PID 2>/dev/null
    sleep 0.5
fi

(sleep 1.2 && open "http://127.0.0.1:8765") &
python3 "./app/server.py"
