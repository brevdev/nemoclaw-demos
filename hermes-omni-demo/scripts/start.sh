#!/usr/bin/env bash
# start.sh — bring up the demo on a single port.
#
# What it does:
#   1. Verify host media helpers are installed
#   2. Verify the sandbox is Ready
#   3. Install UI dependencies if missing
#   4. Build the UI if dist/ is missing
#   5. Create/use a local Python virtualenv for server deps
#   6. Run uvicorn — it serves both /api/* and the built UI from one port
#
# Open http://<host>:8765 in a browser.
#
# Usage:
#   SANDBOX=my-hermes bash scripts/start.sh
#
# Optional:
#   VENV_DIR=.venv PORT=8766 HOST=127.0.0.1 bash scripts/start.sh
#
# To stop:  bash scripts/stop.sh   (or Ctrl-C if you ran in foreground)
set -euo pipefail

SANDBOX="${SANDBOX:-my-hermes}"
PORT="${PORT:-8765}"
HOST="${HOST:-0.0.0.0}"
HERE=$(cd "$(dirname "$0")/.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$HERE/.venv}"

echo "→ sandbox: $SANDBOX"
echo "→ url:     http://localhost:$PORT"
echo

# ── 0. host helper commands ──
missing=()
for cmd in ffmpeg ffprobe pdftoppm lsof "$PYTHON_BIN" npm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing+=("$cmd")
    fi
done
if (( ${#missing[@]} > 0 )); then
    echo "✗ missing host command(s): ${missing[*]}" >&2
    echo "  Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y ffmpeg poppler-utils lsof python3-venv" >&2
    echo "  Also make sure Node/npm are installed and on PATH." >&2
    exit 1
fi

# ── 1. sandbox Ready? ──
# `nemoclaw status` colors its output with ANSI escapes that sit between
# "Phase:" and "Ready", so strip them before matching.
status_out=$(nemoclaw "$SANDBOX" status 2>&1 | sed 's/\x1b\[[0-9;]*m//g')
if ! grep -q "Phase:[[:space:]]*Ready" <<<"$status_out"; then
    echo "✗ sandbox '$SANDBOX' is not Ready."
    echo "  Run:  nemoclaw $SANDBOX status"
    echo "  or:   nemoclaw onboard --agent hermes"
    exit 1
fi
echo "✓ sandbox Ready"

# ── 2. UI deps ──
if [[ ! -d "$HERE/ui/node_modules" ]]; then
    echo "→ installing UI dependencies (one-time, ~30s)"
    (cd "$HERE/ui" && npm install --silent)
fi

# ── 3. UI build ──
if [[ ! -d "$HERE/ui/dist" ]] || [[ "$HERE/ui/src" -nt "$HERE/ui/dist" ]]; then
    echo "→ building UI"
    (cd "$HERE/ui" && npm run build)
fi
echo "✓ UI built at $HERE/ui/dist"

# ── 4. server deps in local virtualenv ──
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "→ creating Python virtualenv at $VENV_DIR"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        echo "✗ failed to create virtualenv. On Ubuntu/Debian install python3-venv:" >&2
        echo "  sudo apt-get update && sudo apt-get install -y python3-venv" >&2
        exit 1
    fi
fi
PYTHON="$VENV_DIR/bin/python"
if ! "$PYTHON" -c "import fastapi, uvicorn, yaml, multipart" 2>/dev/null; then
    echo "→ installing server dependencies into $VENV_DIR (one-time)"
    "$PYTHON" -m pip install --quiet -r "$HERE/server/requirements.txt"
fi
echo "✓ server deps ready ($PYTHON)"

# ── 5. port available? ──
if lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n 2>/dev/null | grep -q LISTEN; then
    echo "✗ port $PORT already in use"
    echo "  Stop the other process or set PORT=<other> and try again."
    exit 1
fi

# ── 6. run uvicorn (serves API + built UI on the same port) ──
echo
echo "→ launching server"
echo "  open http://localhost:$PORT in your browser"
echo "  Ctrl-C to stop"
echo
cd "$HERE/server"
exec env SANDBOX="$SANDBOX" \
    "$PYTHON" -m uvicorn server:app --host "$HOST" --port "$PORT"
