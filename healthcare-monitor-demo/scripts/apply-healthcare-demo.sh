#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/.env"
  set +a
fi

SANDBOX="${NEMOCLAW_SANDBOX:-healthcare-monitor}"

echo "Applying/validating Healthcare Monitor Demo for sandbox: $SANDBOX"
"$ROOT/scripts/apply-demo-policy.sh"

echo
echo "Agents:"
openshell sandbox exec --name "$SANDBOX" -- openclaw agents list || true

echo
echo "Image-baked topology:"
openshell sandbox exec --name "$SANDBOX" -- \
  python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py agent-topology

echo
echo "OpenClaw config:"
"$ROOT/scripts/show-sandbox-config.sh"
