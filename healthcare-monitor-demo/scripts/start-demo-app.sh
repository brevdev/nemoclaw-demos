#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/.env"
  set +a
fi

PORT="${PORT:-5188}"
HOST="${HOST:-127.0.0.1}"

echo "Starting healthcare monitor web app."
echo "URL: http://${HOST}:${PORT}"
echo "Press Ctrl+C to stop."

cd "$ROOT"
HOST="$HOST" PORT="$PORT" python3 demo-app/server.py

