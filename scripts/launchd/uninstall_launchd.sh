#!/bin/bash
# Uninstaller for the digital-dad DAILY product-dev launchd agent.
# Boots out the agent, removes the installed plist, and removes the staged
# trampoline. Safe to re-run (each step is best-effort).
#
# Does NOT touch the weekly cron (com.calhoun.digitaldad-weekly).

set -uo pipefail

LABEL="com.calhoun.digitaldad-daily"
STAGE_DIR="$HOME/digital-dad-launchers"
STAGED_TRAMPOLINE="$STAGE_DIR/daily_routine.sh"
DEST_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null && echo "Booted out $GUI_DOMAIN/$LABEL" \
  || echo "Agent not loaded (ok)"

if [ -f "$DEST_PLIST" ]; then
  rm -f "$DEST_PLIST"
  echo "Removed plist       → $DEST_PLIST"
else
  echo "No plist to remove (ok)"
fi

if [ -f "$STAGED_TRAMPOLINE" ]; then
  rm -f "$STAGED_TRAMPOLINE"
  echo "Removed trampoline  → $STAGED_TRAMPOLINE"
  rmdir "$STAGE_DIR" 2>/dev/null || true
else
  echo "No staged trampoline to remove (ok)"
fi

echo "Done. (Full Disk Access entry for /bin/bash, if added, can be removed manually.)"
