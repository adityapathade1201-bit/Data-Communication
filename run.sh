#!/usr/bin/env bash
# NetPulse: install dependencies and start backend (port 8000) + frontend (port 5173).
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "Python 3.11+ is required (set PYTHON=...)"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 18+ and npm are required"; exit 1; }

echo "==> Backend: creating virtualenv and installing dependencies"
if [ ! -d backend/.venv ]; then "$PY" -m venv backend/.venv; fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

echo "==> Frontend: installing dependencies"
(cd frontend && npm install --no-audit --no-fund)

cleanup() { echo; echo "Stopping NetPulse…"; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "==> Starting backend on http://localhost:8000"
(cd backend && exec uvicorn app.main:app --host 0.0.0.0 --port 8000) &
sleep 2
echo "==> Starting frontend on http://localhost:5173   (open this in your browser)"
(cd frontend && exec npm run dev -- --host) &
wait
