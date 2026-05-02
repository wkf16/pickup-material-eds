#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${1:-a203@203-precision3660}"
REMOTE_DIR="${2:-/home/a203/pickup-material-eds-webui}"
PORT="${PICKUP_EDS_PORT:-8000}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[1/3] rsync -> ${REMOTE_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'data/catalog.sqlite3' \
  --exclude 'data/recordings' \
  "${ROOT_DIR}/" "${REMOTE_HOST}:${REMOTE_DIR}/"

echo "[2/3] install/update remote venv"
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${REMOTE_HOST}" "
  set -euo pipefail
  mkdir -p '${REMOTE_DIR}'
  cd '${REMOTE_DIR}'
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e .
  mkdir -p data/recordings
"

echo "[3/3] restart uvicorn on remote"
# port < 1024 requires sudo; password sourced from SUDO_PASS env or prompted
SUDO_PASS="${SUDO_PASS:-}"
if [ "${PORT}" -lt 1024 ]; then
  SUDO_PREFIX="echo '${SUDO_PASS}' | sudo -S"
  SUDO_KILL="echo '${SUDO_PASS}' | sudo -S"
else
  SUDO_PREFIX=""
  SUDO_KILL=""
fi
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${REMOTE_HOST}" "
  set -euo pipefail
  cd '${REMOTE_DIR}'
  if [ -f webui.pid ] && ${SUDO_KILL:-} kill -0 \$(cat webui.pid) 2>/dev/null; then
    ${SUDO_KILL:-} kill \$(cat webui.pid) || true
    sleep 1
  fi
  if command -v fuser >/dev/null 2>&1; then
    ${SUDO_KILL:-} fuser -k ${PORT}/tcp 2>/dev/null || true
    sleep 1
  elif command -v ss >/dev/null 2>&1; then
    pids=\$(ss -ltnp 2>/dev/null | awk '/:${PORT} / {match(\$NF,/pid=([0-9]+)/,a); if(a[1]) print a[1]}')
    [ -n \"\${pids}\" ] && ${SUDO_KILL:-} kill \${pids} || true
    sleep 1
  fi
  PYTHON_BIN='${REMOTE_DIR}/.venv/bin/python'
  ${SUDO_PREFIX:-} nohup "\${PYTHON_BIN}" -m uvicorn pickup_eds.api.main:app --host 0.0.0.0 --port '${PORT}' > webui.log 2>&1 &
  echo \$! > webui.pid
  sleep 2
  curl -fsS http://127.0.0.1:${PORT}/api/health
"

echo "remote webui is up on port ${PORT}"
