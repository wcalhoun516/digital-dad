#!/bin/bash
# Trampoline for the digital-dad WEEKLY cron (scrape / analyze / dashboard).
#
# launchd invokes a COPY of this script staged on the SYSTEM DISK
# (~/digital-dad-launchers/weekly_run.sh) — never a path on the external
# volume. This matters for two reasons:
#   1. The job can start before /Volumes/FamilyWorkDrive mounts; it then waits.
#   2. The plist's StandardOut/ErrorPath stay on /tmp. The previous weekly plist
#      pointed those at .../digital-dad/data/cron/launchd.{out,err}; when the job
#      fired while the volume was unmounted, launchd recreated
#      /Volumes/FamilyWorkDrive as a real directory on the boot disk to hold the
#      log. That squatter bumped the real volume to "FamilyWorkDrive 1" on the
#      next mount, breaking every absolute path on the drive. See the icedge
#      repo's docs/gotchas.md for the full post-mortem.
#
# Manual run:   bash ~/digital-dad-launchers/weekly_run.sh
#
# Requires: /bin/bash has Full Disk Access (System Settings → Privacy &
# Security → Full Disk Access), since the repo lives on an external volume.

set -u

PROJECT_ROOT="${DIGITAL_DAD_ROOT:-/Volumes/FamilyWorkDrive/development/digital-dad}"
VOLUME_ROOT="/Volumes/FamilyWorkDrive"
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

# Hand off to the real on-volume runner, which owns its own logging into
# data/cron/weekly.log.
exec /bin/bash "$PROJECT_ROOT/bin/weekly_run.sh"
