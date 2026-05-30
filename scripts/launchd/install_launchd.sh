#!/bin/bash
# Idempotent installer for the digital-dad DAILY product-dev launchd agent.
#
# 1. Stages the trampoline onto the SYSTEM DISK (~/digital-dad-launchers/) so the
#    job can start before the external volume mounts.
# 2. Writes the plist into ~/Library/LaunchAgents/, substituting the staged path.
# 3. Boots out any existing copy, then bootstraps the new one.
# 4. Prints the one-time Full Disk Access grant (external volume → /bin/bash needs it).
#
# Safe to re-run. Does NOT touch the weekly cron (com.calhoun.digitaldad-weekly).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.calhoun.digitaldad-daily"
SRC_PLIST="$SCRIPT_DIR/$LABEL.plist"
SRC_TRAMPOLINE="$SCRIPT_DIR/trampolines/daily_routine.sh"

STAGE_DIR="$HOME/digital-dad-launchers"
STAGED_TRAMPOLINE="$STAGE_DIR/daily_routine.sh"
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
echo "Next scheduled run (01:00 daily):"
launchctl print "$GUI_DOMAIN/$LABEL" 2>/dev/null \
  | grep -E "next|state|last exit code" \
  || echo "  (run 'launchctl print $GUI_DOMAIN/$LABEL' for details)"

cat <<EOF

------------------------------------------------------------------------------
ONE-TIME Full Disk Access grant (required — repo is on an external volume):

  System Settings → Privacy & Security → Full Disk Access → enable an entry
  for /bin/bash. To add it: click "+", press Cmd-Shift-G, enter /bin/bash,
  add it, and toggle it on. Without this, the scheduled job cannot read the
  repo on /Volumes/FamilyWorkDrive when it fires unattended.
------------------------------------------------------------------------------

Safe verification (opens NO PR):
  DAILY_ROUTINE_DRY_RUN=1 bash "$STAGED_TRAMPOLINE"
  tail -n 40 "/Volumes/FamilyWorkDrive/development/digital-dad/logs/daily_routine_\$(date +%Y%m%d).log"

Manage:
  launchctl print     $GUI_DOMAIN/$LABEL
  launchctl kickstart -k $GUI_DOMAIN/$LABEL    # fires a REAL run → opens a draft PR
  launchctl bootout   $GUI_DOMAIN/$LABEL       # stop (or run uninstall_launchd.sh)
EOF
