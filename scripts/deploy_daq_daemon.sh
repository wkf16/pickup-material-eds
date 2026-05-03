#!/usr/bin/env bash
# Push the daq_daemon package + supporting modules to pickup-win10-ltsc
# and (re)register the PickupEdsDaqDaemon scheduled task.
#
# Idempotent. Re-runs do a fresh rsync + venv refresh.
#
# Usage:
#   scripts/deploy_daq_daemon.sh [LAB_HOST]
#
# LAB_HOST defaults to lab4070-c. The script ssh-es to LAB_HOST, copies
# the package there, then uses ~/winrm-venv to push files into the VM.

set -euo pipefail

LAB_HOST="${1:-lab4070-c}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_ROOT"

# Files we need on the VM:
#   src/pickup_eds/__init__.py
#   src/pickup_eds/schemas.py
#   src/pickup_eds/config.py
#   src/pickup_eds/daq_daemon/*.py
# We bundle them into a tarball, push to lab, then base64-into the VM.
STAGE=$(mktemp -d)
trap "rm -rf $STAGE" EXIT

mkdir -p "$STAGE/pickup_eds/daq_daemon"
cp src/pickup_eds/__init__.py        "$STAGE/pickup_eds/"
cp src/pickup_eds/schemas.py         "$STAGE/pickup_eds/"
cp src/pickup_eds/config.py          "$STAGE/pickup_eds/"
cp src/pickup_eds/daq_daemon/*.py    "$STAGE/pickup_eds/daq_daemon/"

# Manifest of (relative_path, target) pairs for winrm_push.py put.
( cd "$STAGE" && find pickup_eds -type f -name '*.py' )

# Tarball the staged tree
TARBALL="$STAGE/daq_daemon_pkg.tar.gz"
( cd "$STAGE" && tar czf daq_daemon_pkg.tar.gz pickup_eds )

# ── Stage 1: ship to lab4070 (via campus ssh) ────────────────────────
echo ">> rsyncing daq_daemon package to $LAB_HOST"
scp "$TARBALL" "$LAB_HOST:/tmp/daq_daemon_pkg.tar.gz"
scp scripts/winrm_push.py "$LAB_HOST:/tmp/winrm_push.py"
scp deploy/win/install-daq-daemon-task.ps1 "$LAB_HOST:/tmp/install-daq-daemon-task.ps1"
scp deploy/win/setup-daq-daemon.ps1 "$LAB_HOST:/tmp/setup-daq-daemon.ps1"

# ── Stage 2: push from lab4070 → VM via WinRM ─────────────────────────
echo ">> uploading bundle into VM (this may take ~60 s due to base64 chunking)"
ssh "$LAB_HOST" bash -lc '
set -e
~/winrm-venv/bin/python /tmp/winrm_push.py put /tmp/daq_daemon_pkg.tar.gz "C:/setup/daq_daemon_pkg.tar.gz"
~/winrm-venv/bin/python /tmp/winrm_push.py put /tmp/install-daq-daemon-task.ps1 "C:/setup/install-daq-daemon-task.ps1"
~/winrm-venv/bin/python /tmp/winrm_push.py put /tmp/setup-daq-daemon.ps1 "C:/setup/setup-daq-daemon.ps1"
'

# ── Stage 3: extract + venv + scheduled task on the VM ───────────────
echo ">> running setup-daq-daemon.ps1 on VM"
ssh "$LAB_HOST" bash -lc "~/winrm-venv/bin/python /tmp/winrm_push.py ps /tmp/setup-daq-daemon.ps1"

echo ">> registering scheduled task"
ssh "$LAB_HOST" bash -lc "~/winrm-venv/bin/python /tmp/winrm_push.py ps /tmp/install-daq-daemon-task.ps1"

echo "Done. Use scripts/verify_daq_daemon.sh to test."
