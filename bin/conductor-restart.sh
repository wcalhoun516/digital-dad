#!/bin/bash
# Restart the local-llm-conductor, clearing stale WAL files if needed.
# Usage: bash bin/conductor-restart.sh

CONDUCTOR_DB="/Volumes/FamilyWorkDrive/development/local-llm-conductor/data/conductor.db"

echo "Stopping conductor..."
# Kill ALL matching processes (pkill can miss reparented ones)
pids=$(pgrep -f "uvicorn app.main:app" 2>/dev/null)
if [ -n "$pids" ]; then
  echo "  Killing PIDs: $pids"
  kill -9 $pids 2>/dev/null
fi
sleep 2

# Clear stale WAL/SHM files that cause "database is locked" after a crash
if [ -f "${CONDUCTOR_DB}-wal" ] || [ -f "${CONDUCTOR_DB}-shm" ]; then
  echo "Clearing stale WAL/SHM files..."
  rm -f "${CONDUCTOR_DB}-shm" "${CONDUCTOR_DB}-wal"
fi

echo "Starting conductor..."
cd /Volumes/FamilyWorkDrive/development/local-llm-conductor
OLLAMA_MODELS=/Volumes/FamilyWorkDrive/ollama/ /usr/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080 &
sleep 3

if curl -sf http://127.0.0.1:8080/health > /dev/null 2>&1; then
  echo "Conductor is healthy at http://127.0.0.1:8080"
  echo "Dashboard: http://127.0.0.1:8080/dashboard/"
else
  echo "ERROR: Conductor failed to start"
  exit 1
fi
