#!/bin/bash
# Idempotent installer for the digital-dad WEEKLY launchd agent.
#
# 1. Stages the trampoline onto the SYSTEM DISK (~/digital-dad-launchers/) so the
#    job can start before the external volume mounts.
# 2. Writes the plist into ~/Library/LaunchAgents/, substituting the staged path.
# 3. Boots out any existing copy, then bootstraps the new one.
#
# Safe to re-run. The plist keeps launchd's StandardOut/ErrorPath on /tmp so the
# job can never recreate the volume mountpoint as a squatter dir (see
# trampolines/weekly_run.sh for the post-mortem).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.calhoun.digitaldad-weekly"
SRC_PLIST="$SCRIPT_DIR/$LABEL.plist"
SRC_TRAMPOLINE="$SCRIPT_DIR/trampolines/weekly_run.sh"

STAGE_DIR="$HOME/digital-dad-launchers"
STAGED_TRAMPOLINE="$STAGE_DIR/weekly_run.sh"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

[ -f "$SRC_PLIST" ]      || { echo "Error: plist not found at $SRC_PLIST" >&2; exit 1; }
[ -f "$SRC_TRAMPOLINE" ] || { echo "Error: trampoline not found at $SRC_TRAMPOLINE" >&2; exit 1; }

# 1. Stage the trampoline on the system disk.
mkdir -p "$STAGE_DIR"
cp "$SRC_TRAMPOLINE" "$STAGED_TRAMPOLINE"
chmod +x "$STAGED_TRAMPOLINE"
echo "Staged trampoline   → $STAGED_TRAMPOLINE"

# 2. Write the plist with the staged path substituted in.
mkdir -p "$DEST_DIR"
sed "s|__TRAMPOLINE_PATH__|$STAGED_TRAMPOLINE|g" "$SRC_PLIST" > "$DEST_PLIST"
echo "Installed plist     → $DEST_PLIST"

# 3. Reload (idempotent).
launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$GUI_DOMAIN" "$DEST_PLIST"
launchctl enable "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
echo "Bootstrapped agent  → $GUI_DOMAIN/$LABEL"

echo ""
echo "Next scheduled run (Sunday 03:00):"
launchctl print "$GUI_DOMAIN/$LABEL" 2>/dev/null \
  | grep -E "next|state|last exit code" \
  || echo "  (run 'launchctl print $GUI_DOMAIN/$LABEL' for details)"

cat <<EOF

Logs:
  launchd wrapper : /tmp/digitaldad_weekly.{out,err}.log
  run log         : /Volumes/FamilyWorkDrive/development/digital-dad/data/cron/weekly.log

Manage:
  launchctl print     $GUI_DOMAIN/$LABEL
  launchctl kickstart -k $GUI_DOMAIN/$LABEL    # fire a REAL run now
  launchctl bootout   $GUI_DOMAIN/$LABEL       # stop
EOF
