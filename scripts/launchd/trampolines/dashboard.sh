#!/bin/bash
# Trampoline for the digital-dad DASHBOARD share service (password-gated static
# server + conductor proxy, bound to localhost). Tailscale Funnel — set up
# separately by install_dashboard.sh — is what exposes it publicly over HTTPS;
# binding 127.0.0.1 keeps it off the raw LAN/internet so the ONLY way in is the
# Funnel link, which the password gate then protects.
#
# launchd invokes a COPY of this script staged on the SYSTEM DISK
# (~/digital-dad-launchers/dashboard.sh) so the service can start before
# /Volumes/FamilyWorkDrive mounts; it then waits for the volume. (See the weekly
# trampoline for why logs + the staged copy must live off the external volume.)
#
# Manual run:   bash ~/digital-dad-launchers/dashboard.sh
#
# Requires: /bin/bash has Full Disk Access (System Settings → Privacy &
# Security → Full Disk Access), since the repo lives on an external volume.

set -u

PROJECT_ROOT="${DIGITAL_DAD_ROOT:-/Volumes/FamilyWorkDrive/development/digital-dad}"
VOLUME_ROOT="/Volumes/FamilyWorkDrive"
PORT="${DIGITAL_DAD_SHARE_PORT:-8000}"
ADDRESS="${DIGITAL_DAD_SHARE_ADDRESS:-127.0.0.1}"
PASSWORD_FILE="${DIGITAL_DAD_DASHBOARD_PASSWORD_FILE:-$HOME/.config/digital-dad/dashboard_password}"
MOUNT_WAIT_SECONDS=90

# launchd gives a minimal PATH; rebuild a useful one.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Wait for the external volume to mount.
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

VENV_PY="$PROJECT_ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || { echo "ERROR: venv python missing at $VENV_PY" >&2; exit 1; }

# Secrets: dashboard password. Without it the server REFUSES to start (it would
# otherwise be unauthenticated) — never run the public Funnel without this file.
if [ -f "$PASSWORD_FILE" ]; then
  DIGITAL_DAD_DASHBOARD_PASSWORD="$(tr -d '\n' < "$PASSWORD_FILE")"
  export DIGITAL_DAD_DASHBOARD_PASSWORD
else
  echo "ERROR: no password file at $PASSWORD_FILE — refusing to serve unprotected." >&2
  echo "       Run scripts/launchd/install_dashboard.sh to create it." >&2
  exit 1
fi

export DIGITAL_DAD_SHARE_PORT="$PORT"
export DIGITAL_DAD_SHARE_ADDRESS="$ADDRESS"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] dashboard share serving $ADDRESS:$PORT (waited=${waited}s)"

exec "$VENV_PY" "$PROJECT_ROOT/bin/serve_dashboard.py"
