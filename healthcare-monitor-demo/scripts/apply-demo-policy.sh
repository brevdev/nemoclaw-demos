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

echo "Applying healthcare monitor local policy to sandbox: $SANDBOX"
nemoclaw "$SANDBOX" policy-add --from-file "$ROOT/policy.yaml" --yes
echo "Policy apply complete."
