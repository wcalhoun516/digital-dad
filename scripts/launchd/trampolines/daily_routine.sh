#!/bin/bash
# Trampoline for the digital-dad daily product-development agent.
#
# launchd invokes a COPY of this script staged on the system disk
# (~/digital-dad-launchers/daily_routine.sh) so the job can start even before
# the external volume mounts. This script then waits for the volume, sets up
# PATH, sanity-checks the toolchain, and runs Claude headlessly against
# scripts/daily_routine_prompt.md to produce one draft PR.
#
# Manual run:        bash ~/digital-dad-launchers/daily_routine.sh
# Safe dry run:      DAILY_ROUTINE_DRY_RUN=1 bash ~/digital-dad-launchers/daily_routine.sh
#   (dry run does all preflight + logs the exact claude command, but does NOT
#    invoke claude and therefore opens no PR — used for install verification.)

set -u

# --- Configuration ----------------------------------------------------------
PROJECT_ROOT="${DIGITAL_DAD_ROOT:-/Volumes/FamilyWorkDrive/development/digital-dad}"
VOLUME_ROOT="/Volumes/FamilyWorkDrive"
PROMPT_REL="scripts/daily_routine_prompt.md"
CLAUDE_MODEL="claude-opus-4-8"
CLAUDE_EFFORT="high"
MOUNT_WAIT_SECONDS=90

# --- PATH (launchd gives a minimal PATH; rebuild a useful one) --------------
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# --- Wait for the external volume to mount ----------------------------------
waited=0
while [ ! -d "$VOLUME_ROOT" ] || [ ! -d "$PROJECT_ROOT" ]; do
  if [ "$waited" -ge "$MOUNT_WAIT_SECONDS" ]; then
    echo "ERROR: $PROJECT_ROOT not available after ${MOUNT_WAIT_SECONDS}s — volume not mounted?" >&2
    exit 1
  fi
  sleep 3
  waited=$((waited + 3))
done

cd "$PROJECT_ROOT" || { echo "ERROR: cannot cd to $PROJECT_ROOT" >&2; exit 1; }

# --- Logging ----------------------------------------------------------------
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_routine_$(date +%Y%m%d).log"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

log "=========================================================="
log "daily_routine start (pid $$)  project_root=$PROJECT_ROOT  waited_for_mount=${waited}s"

# --- Toolchain sanity checks ------------------------------------------------
fail() { log "ERROR: $*"; log "daily_routine ABORTED"; exit 1; }

command -v claude >/dev/null 2>&1 || fail "'claude' not found on PATH ($PATH)"
command -v gh     >/dev/null 2>&1 || fail "'gh' not found on PATH ($PATH)"
log "claude: $(command -v claude)    gh: $(command -v gh)"

if ! gh auth status >/dev/null 2>&1; then
  fail "'gh auth status' is not green — GitHub auth missing/expired"
fi
log "gh auth: OK"

[ -f "$PROJECT_ROOT/$PROMPT_REL" ] || fail "prompt file missing: $PROMPT_REL"

CLAUDE_CMD="claude --model $CLAUDE_MODEL --effort $CLAUDE_EFFORT --dangerously-skip-permissions --print"

# --- Dry run: prove everything loads without firing the agent ---------------
if [ "${DAILY_ROUTINE_DRY_RUN:-0}" = "1" ]; then
  log "DRY RUN — preflight passed. Would run:"
  log "    $CLAUDE_CMD < $PROMPT_REL"
  log "DRY RUN — skipping claude invocation (no PR opened)."
  log "daily_routine end (dry run, exit=0)"
  exit 0
fi

# --- Real run ---------------------------------------------------------------
log "invoking: $CLAUDE_CMD < $PROMPT_REL"
$CLAUDE_CMD < "$PROJECT_ROOT/$PROMPT_REL" >>"$LOG_FILE" 2>&1
rc=$?
log "claude exited rc=$rc"
log "daily_routine end (exit=$rc)"
exit "$rc"
