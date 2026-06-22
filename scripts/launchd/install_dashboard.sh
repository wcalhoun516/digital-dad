#!/bin/bash
# Idempotent installer for the digital-dad DASHBOARD share service + Tailscale
# Funnel public link. Lets someone on any network/device open the dashboard by
# clicking ONE https link and entering a password — no install on their end.
#
# 1. Writes the dashboard password (600 perms) if one doesn't exist yet.
#    Default password is "GeoLLM"; override with --password <pw> or the
#    DIGITAL_DAD_DASHBOARD_PASSWORD env var. --rotate-password rewrites it.
# 2. Stages the trampoline onto the SYSTEM DISK (so it starts before the external
#    volume mounts) and writes the plist into ~/Library/LaunchAgents/.
# 3. Boots out any existing copy, then bootstraps the new one (KeepAlive).
# 4. If Tailscale is up, enables a persistent Funnel on PUBLIC PORT 8443
#    (public HTTPS :8443 → localhost:8000). Public 443 is intentionally left
#    alone so a co-resident Funnel there (e.g. another dashboard) is untouched.
#
# Safe to re-run. Does NOT touch the weekly/daily agents.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.calhoun.digitaldad-dashboard"
SRC_PLIST="$SCRIPT_DIR/$LABEL.plist"
SRC_TRAMPOLINE="$SCRIPT_DIR/trampolines/dashboard.sh"

LOCAL_PORT="${DIGITAL_DAD_SHARE_PORT:-8000}"
PUBLIC_PORT="${DIGITAL_DAD_FUNNEL_PORT:-8443}"   # Funnel allows 443, 8443, 10000

STAGE_DIR="$HOME/digital-dad-launchers"
STAGED_TRAMPOLINE="$STAGE_DIR/dashboard.sh"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/$LABEL.plist"
GUI_DOMAIN="gui/$(id -u)"

SECRET_DIR="$HOME/.config/digital-dad"
PASSWORD_FILE="$SECRET_DIR/dashboard_password"

# Default password (the user picked this); overridable.
NEW_PASSWORD="${DIGITAL_DAD_DASHBOARD_PASSWORD:-GeoLLM}"
ROTATE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --rotate-password) ROTATE=1 ;;
    --password) shift; NEW_PASSWORD="${1:-}" ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

TS="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
command -v tailscale >/dev/null 2>&1 && TS="$(command -v tailscale)"

# Portable timeout: `tailscale status` blocks indefinitely when the daemon is up
# but not yet logged in, so never call it bare. (macOS has no coreutils timeout.)
_with_timeout() {
  local secs="$1"; shift
  "$@" & local pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null ) & local watcher=$!
  wait "$pid" 2>/dev/null; local rc=$?
  kill "$watcher" 2>/dev/null; wait "$watcher" 2>/dev/null || true
  return "$rc"
}

[ -f "$SRC_PLIST" ]      || { echo "Error: plist not found at $SRC_PLIST" >&2; exit 1; }
[ -f "$SRC_TRAMPOLINE" ] || { echo "Error: trampoline not found at $SRC_TRAMPOLINE" >&2; exit 1; }

# 1. Password.
mkdir -p "$SECRET_DIR"; chmod 700 "$SECRET_DIR"
if [ "$ROTATE" = "1" ] || [ ! -f "$PASSWORD_FILE" ]; then
  printf '%s' "$NEW_PASSWORD" > "$PASSWORD_FILE"
  chmod 600 "$PASSWORD_FILE"
  echo "Wrote password      → $PASSWORD_FILE"
else
  echo "Password exists     → $PASSWORD_FILE (use --rotate-password or --password to change)"
fi

# 2. Stage trampoline + write plist.
mkdir -p "$STAGE_DIR"
cp "$SRC_TRAMPOLINE" "$STAGED_TRAMPOLINE"
chmod +x "$STAGED_TRAMPOLINE"
echo "Staged trampoline   → $STAGED_TRAMPOLINE"

mkdir -p "$DEST_DIR"
sed "s|__TRAMPOLINE_PATH__|$STAGED_TRAMPOLINE|g" "$SRC_PLIST" > "$DEST_PLIST"
echo "Installed plist     → $DEST_PLIST"

# 3. Reload (idempotent).
launchctl bootout "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$GUI_DOMAIN" "$DEST_PLIST"
launchctl enable "$GUI_DOMAIN/$LABEL" 2>/dev/null || true
echo "Bootstrapped agent  → $GUI_DOMAIN/$LABEL (serving 127.0.0.1:$LOCAL_PORT)"

# 4. Funnel on a dedicated public port so other Funnels stay put.
echo ""
if [ -x "$TS" ] && _with_timeout 8 "$TS" status >/dev/null 2>&1; then
  echo "Tailscale is up — enabling persistent Funnel (public HTTPS :$PUBLIC_PORT → :$LOCAL_PORT)…"
  if _with_timeout 30 "$TS" funnel --bg --https="$PUBLIC_PORT" "$LOCAL_PORT" 2>/tmp/digitaldad_funnel.err; then
    echo ""
    echo "PUBLIC LINK:"
    _with_timeout 8 "$TS" funnel status 2>/dev/null || true
  else
    echo "Funnel command failed — see /tmp/digitaldad_funnel.err. Most likely you still"
    echo "need HTTPS certificates + the Funnel node-attribute enabled in the admin"
    echo "console: https://login.tailscale.com/admin/settings/keys"
    cat /tmp/digitaldad_funnel.err >&2 || true
  fi
else
  cat <<EOF
Tailscale not logged in yet. Finish these, then re-run this script:
  1. Open the Tailscale menu-bar app → "Log in…" → authenticate in the browser.
  2. Admin console → enable MagicDNS and HTTPS Certificates:
       https://login.tailscale.com/admin/dns
  3. Enable Funnel for this machine.
EOF
fi

cat <<EOF

------------------------------------------------------------------------------
Dashboard password (share with whoever you invite):
  $(cat "$PASSWORD_FILE")

The public link is the https://<machine>.<tailnet>.ts.net:$PUBLIC_PORT URL above.
Send the recipient: that link + the password. Works on any network/device.
------------------------------------------------------------------------------

Manage:
  launchctl kickstart -k $GUI_DOMAIN/$LABEL    # restart the dashboard server
  launchctl bootout   $GUI_DOMAIN/$LABEL       # stop the dashboard server
  $TS funnel status                            # show / confirm the public link
  $TS funnel --https=$PUBLIC_PORT off          # take THIS public link DOWN
  tail -n 40 /tmp/digitaldad_dashboard.err.log # logs
  $0 --rotate-password                         # change the password
EOF
