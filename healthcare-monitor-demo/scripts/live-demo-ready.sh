#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f ".env" ]]; then
  echo "Missing .env. Create it first:"
  echo "  cp .env.example .env"
  echo "  vi .env"
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

SANDBOX="${NEMOCLAW_SANDBOX:-healthcare-monitor}"
PORT="${PORT:-5188}"
HOST="${HOST:-127.0.0.1}"

echo "1/6 Verifying local image build context and deterministic outputs."
./scripts/run-local-verification.sh

if [[ "${NEMOCLAW_ALLOW_PROVIDER_OVERRIDE:-0}" == "1" && "${NEMOCLAW_PROVIDER:-build}" != "build" ]]; then
  echo "2/6 Using provider override: ${NEMOCLAW_PROVIDER}. Skipping NVIDIA build endpoint probe."
else
  echo "2/6 Probing NVIDIA build endpoint."
  ./scripts/probe-build-endpoint.sh
fi

echo "3/6 Checking NemoClaw sandbox status."
nemoclaw "$SANDBOX" status >/tmp/healthcare-monitor-nemoclaw-status.txt
grep -E "Sandbox:|Model:|Provider:|Inference:|OpenClaw:|Phase:" /tmp/healthcare-monitor-nemoclaw-status.txt || cat /tmp/healthcare-monitor-nemoclaw-status.txt

echo "4/6 Probing OpenClaw gateway."
nemoclaw "$SANDBOX" connect --probe-only

echo "5/6 Applying local policy."
./scripts/apply-demo-policy.sh

echo "6/6 Starting web app in the background if needed."
if curl -fsS "http://${HOST}:${PORT}/api/config" >/dev/null 2>&1; then
  echo "Web app is already running at http://${HOST}:${PORT}"
else
  nohup env HOST="$HOST" PORT="$PORT" python3 demo-app/server.py > /tmp/healthcare-monitor-app.log 2>&1 &
  sleep 1
  curl -fsS "http://${HOST}:${PORT}/api/config" >/dev/null
  echo "Web app started at http://${HOST}:${PORT}"
  echo "Log: /tmp/healthcare-monitor-app.log"
fi

cat <<EOF

Ready.

Open the web app:
  http://${HOST}:${PORT}

Open the OpenShell TUI in a second terminal:
  cd $ROOT
  ./scripts/open-openshell-tui.sh

Available web app sections:
  01 Runtime
  02 Architecture
  03 Evidence
  04 Operations
  05 Governance
EOF
