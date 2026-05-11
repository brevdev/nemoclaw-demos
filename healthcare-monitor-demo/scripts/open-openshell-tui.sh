#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/.env"
  set +a
fi

if ! command -v openshell >/dev/null 2>&1; then
  echo "openshell is not installed or is not on PATH." >&2
  exit 1
fi

echo "Opening OpenShell TUI. Use this to inspect sandbox activity and blocked-egress behavior."
cd "$ROOT"
openshell term
