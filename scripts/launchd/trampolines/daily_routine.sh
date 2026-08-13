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
# PROJECT_ROOT is resolved by glob below so a remount under an alternate name
# (e.g. "FamilyWorkDrive 1" if a squatter dir ever bumps the canonical name)
# still works. DIGITAL_DAD_ROOT overrides resolution entirely when set.
PROJECT_ROOT="${DIGITAL_DAD_ROOT:-}"
PROJECT_GLOB="/Volumes/FamilyWorkDrive*/development/digital-dad"
PROMPT_REL="scripts/daily_routine_prompt.md"
# Override with DIGITAL_DAD_MODEL to test a different model without re-staging.
CLAUDE_MODEL="${DIGITAL_DAD_MODEL:-claude-opus-5}"
CLAUDE_EFFORT="high"
MOUNT_WAIT_SECONDS=90

# --- PATH (launchd gives a minimal PATH; rebuild a useful one) --------------
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# --- Wait for the external volume to mount ----------------------------------
# Resolve by glob each iteration: when the volume isn't mounted the pattern
# stays literal (the -d test fails) and we wait; once it mounts under any
# FamilyWorkDrive* name, the first match that actually contains the project wins.
waited=0
while [ -z "$PROJECT_ROOT" ] || [ ! -d "$PROJECT_ROOT" ]; do
  for cand in $PROJECT_GLOB; do
    [ -d "$cand" ] && { PROJECT_ROOT="$cand"; break; }
  done
  [ -n "$PROJECT_ROOT" ] && [ -d "$PROJECT_ROOT" ] && break
  if [ "$waited" -ge "$MOUNT_WAIT_SECONDS" ]; then
    echo "ERROR: no $PROJECT_GLOB after ${MOUNT_WAIT_SECONDS}s — volume not mounted?" >&2
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

# GitHub auth, robust under headless launchd. The login keychain that holds the
# gh keyring token is often locked at 01:00, so the check used to flap (see the
# 2026-05-31 abort). Prefer an explicit token if one is provided — that bypasses
# the keychain entirely — then retry the status check to ride out a keychain
# that's slow to unlock. To make this bulletproof, drop a PAT (scopes: repo,
# workflow) into $GH_TOKEN_FILE with 600 perms; otherwise it falls back to the
# keyring with retries.
GH_TOKEN_FILE="${GH_TOKEN_FILE:-$HOME/.config/digital-dad/gh_token}"
if [ -z "${GH_TOKEN:-}" ] && [ -z "${GITHUB_TOKEN:-}" ] && [ -f "$GH_TOKEN_FILE" ]; then
  GH_TOKEN="$(tr -d '[:space:]' < "$GH_TOKEN_FILE")"
  export GH_TOKEN
  log "gh auth: using token from $GH_TOKEN_FILE"
fi

gh_ok=0
for attempt in 1 2 3 4 5; do
  if gh auth status >/dev/null 2>&1; then gh_ok=1; break; fi
  log "gh auth: not ready (attempt $attempt/5) — retrying in 5s"
  sleep 5
done
[ "$gh_ok" = 1 ] || fail "'gh auth status' not green after 5 tries — populate $GH_TOKEN_FILE or unlock the login keychain"
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
