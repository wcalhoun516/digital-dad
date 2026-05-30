#!/bin/bash
# Weekly Sunday cron — scrape new articles, re-analyze, re-embed, rebuild
# the dashboard. Each step is incremental: the scraper dedupes against
# manifest.json, the analyze CLI fingerprint-skips unchanged modules, and
# semantic_search.py reuses its embedding cache when the corpus hasn't moved.
#
# Invoked by ~/Library/LaunchAgents/com.calhoun.digitaldad-weekly.plist.
# Can also be run manually: bash bin/weekly_run.sh

set -u  # don't set -e — we want to record failures, not abort the chain

# Resolve project root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/data/cron"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/weekly.log"
SUMMARY_FILE="$LOG_DIR/weekly_summary.jsonl"

START_EPOCH=$(date +%s)
START_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Capture the article count before scraping so we can compute "added".
count_articles() {
  if [ -d "$PROJECT_ROOT/data/raw" ]; then
    /bin/ls -1 "$PROJECT_ROOT/data/raw" 2>/dev/null | grep -c '\.json$' || echo 0
  else
    echo 0
  fi
}
ARTICLES_BEFORE=$(count_articles)

{
  echo ""
  echo "=========================================================="
  echo "weekly_run start:  $START_ISO"
  echo "project_root:      $PROJECT_ROOT"
  echo "articles_before:   $ARTICLES_BEFORE"
  echo "=========================================================="
} | tee -a "$LOG_FILE"

# Track exit status of each step; final exit is the worst.
WORST=0
record() {
  local rc=$1
  if [ "$rc" -gt "$WORST" ]; then WORST=$rc; fi
}

run_step() {
  local name="$1"; shift
  echo "" | tee -a "$LOG_FILE"
  echo "--- $name --------------------------------------------" | tee -a "$LOG_FILE"
  "$@" 2>&1 | tee -a "$LOG_FILE"
  local rc=${PIPESTATUS[0]}
  echo "--- $name done (exit=$rc) ----------------------------" | tee -a "$LOG_FILE"
  record "$rc"
  return "$rc"
}

# Ensure conductor is healthy before running analysis steps.
# Stale WAL/SHM files from a prior crash can cause "database is locked" errors.
CONDUCTOR_DB="/Volumes/FamilyWorkDrive/development/local-llm-conductor/data/conductor.db"
if ! curl -sf http://127.0.0.1:8080/v1/embeddings -H "Content-Type: application/json" \
     -d '{"model":"sbert-mpnet-v2","input":"health"}' -o /dev/null 2>/dev/null; then
  echo "Conductor embeddings unhealthy — clearing stale WAL files and restarting..." | tee -a "$LOG_FILE"
  rm -f "${CONDUCTOR_DB}-shm" "${CONDUCTOR_DB}-wal"
  sudo launchctl bootout system/com.calhoun.conductor 2>/dev/null
  sudo launchctl bootstrap system /Library/LaunchDaemons/com.calhoun.conductor.plist 2>/dev/null
  sleep 5
fi

run_step "scrape"       make scrape
run_step "analyze"      make analyze
run_step "dashboard"    make dashboard
run_step "on-this-day"  make on-this-day

ARTICLES_AFTER=$(count_articles)
ARTICLES_ADDED=$((ARTICLES_AFTER - ARTICLES_BEFORE))
END_EPOCH=$(date +%s)
DURATION=$((END_EPOCH - START_EPOCH))
END_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [ "$WORST" -eq 0 ]; then
  STATUS="ok"
else
  STATUS="failed"
fi

{
  echo ""
  echo "=========================================================="
  echo "weekly_run end:    $END_ISO"
  echo "duration_s:        $DURATION"
  echo "articles_added:    $ARTICLES_ADDED"
  echo "status:            $STATUS (worst exit=$WORST)"
  echo "=========================================================="
} | tee -a "$LOG_FILE"

# Append a structured one-liner to the summary file for cheap auditing.
printf '{"timestamp":"%s","articles_before":%d,"articles_after":%d,"articles_added":%d,"duration_s":%d,"status":"%s","worst_exit":%d}\n' \
  "$END_ISO" "$ARTICLES_BEFORE" "$ARTICLES_AFTER" "$ARTICLES_ADDED" "$DURATION" "$STATUS" "$WORST" \
  >> "$SUMMARY_FILE"

exit "$WORST"
