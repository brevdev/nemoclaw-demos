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

openshell sandbox exec --name "$SANDBOX" -- \
  python3 -m json.tool /sandbox/.openclaw/openclaw.json
