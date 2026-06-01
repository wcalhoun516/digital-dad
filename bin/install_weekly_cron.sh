#!/bin/bash
# DEPRECATED. The weekly agent moved to the system-disk trampoline pattern.
#
# The old version of this script installed bin/com.calhoun.digitaldad-weekly.plist
# verbatim — and that plist pointed launchd's StandardOut/ErrorPath at
# .../digital-dad/data/cron/ on the external volume. When the job fired while the
# volume was unmounted, launchd recreated /Volumes/FamilyWorkDrive as a real
# directory on the boot disk, renaming the real mount to "FamilyWorkDrive 1" and
# breaking every absolute path on the drive.
#
# Use the trampoline-based installer instead:
#     scripts/launchd/install_weekly.sh
#
# This shim just forwards to it so old muscle memory / docs still work.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "install_weekly_cron.sh is deprecated → running scripts/launchd/install_weekly.sh" >&2
exec /bin/bash "$PROJECT_ROOT/scripts/launchd/install_weekly.sh"
