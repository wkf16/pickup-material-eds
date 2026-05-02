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
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${REMOTE_HOST}" "
  set -euo pipefail
  cd '${REMOTE_DIR}'
  if [ -f webui.pid ] && kill -0 \$(cat webui.pid) 2>/dev/null; then
    kill \$(cat webui.pid)
    sleep 1
  fi
  . .venv/bin/activate
  nohup python -m uvicorn pickup_eds.api.main:app --host 0.0.0.0 --port '${PORT}' > webui.log 2>&1 &
  echo \$! > webui.pid
  sleep 2
  curl -fsS http://127.0.0.1:${PORT}/api/health
"

echo "remote webui is up on port ${PORT}"
