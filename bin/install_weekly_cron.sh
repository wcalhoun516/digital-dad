#!/bin/bash
# Idempotent installer for the digital-dad weekly launchd agent.
#
# Copies the committed plist into ~/Library/LaunchAgents/, unloads any
# existing version, then bootstraps the new one. Safe to re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.calhoun.digitaldad-weekly"
SRC_PLIST="$SCRIPT_DIR/$LABEL.plist"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

if [ ! -f "$SRC_PLIST" ]; then
  echo "Error: source plist not found at $SRC_PLIST" >&2
  exit 1
fi

# Make sure the cron log dir exists before launchd points its
# StandardOutPath/StandardErrorPath at it.
mkdir -p "$PROJECT_ROOT/data/cron"

mkdir -p "$DEST_DIR"
cp "$SRC_PLIST" "$DEST_PLIST"
echo "Installed plist → $DEST_PLIST"

# Unload any prior version (silent if not loaded).
launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true

launchctl bootstrap "$GUI_DOMAIN" "$DEST_PLIST"
launchctl enable "$GUI_DOMAIN/$LABEL" 2>/dev/null || true

echo ""
echo "Installed and bootstrapped: $LABEL"
echo ""
echo "Next scheduled run:"
launchctl print "$GUI_DOMAIN/$LABEL" 2>/dev/null \
  | grep -E "next|state|last exit code" \
  || echo "  (run 'launchctl print $GUI_DOMAIN/$LABEL' for details)"
echo ""
echo "Logs: $PROJECT_ROOT/data/cron/weekly.log"
echo "      $PROJECT_ROOT/data/cron/launchd.{out,err}"
echo ""
echo "Run manually:    bash $SCRIPT_DIR/weekly_run.sh"
echo "Uninstall:       launchctl bootout $GUI_DOMAIN/$LABEL"
