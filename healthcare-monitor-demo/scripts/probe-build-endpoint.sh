#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/.env"
  set +a
fi

DEFAULT_MODEL="nvidia/nemotron-3-super-120b-a12b"
DEFAULT_ENDPOINT="https://integrate.api.nvidia.com/v1/chat/completions"

MODEL="${NEMOCLAW_MODEL:-$DEFAULT_MODEL}"
ENDPOINT="${NEMOCLAW_ENDPOINT_URL:-$DEFAULT_ENDPOINT}"
KEY="${NVIDIA_API_KEY:-${NEMOCLAW_PROVIDER_KEY:-${COMPATIBLE_API_KEY:-}}}"

if [[ "$MODEL" != "$DEFAULT_MODEL" ]]; then
  echo "Using release model instead of configured NEMOCLAW_MODEL: $DEFAULT_MODEL" >&2
  MODEL="$DEFAULT_MODEL"
fi

if [[ "$ENDPOINT" != "$DEFAULT_ENDPOINT" ]]; then
  echo "Using NVIDIA build endpoint instead of configured NEMOCLAW_ENDPOINT_URL: $DEFAULT_ENDPOINT" >&2
  ENDPOINT="$DEFAULT_ENDPOINT"
fi

if [[ -z "$KEY" ]]; then
  echo "NVIDIA_API_KEY is required. NEMOCLAW_PROVIDER_KEY and COMPATIBLE_API_KEY are also accepted during transition." >&2
  exit 1
fi

if [[ "$ENDPOINT" != */chat/completions ]]; then
  ENDPOINT="${ENDPOINT%/}/chat/completions"
fi

payload="$(mktemp)"
response="$(mktemp)"
trap 'rm -f "$payload" "$response"' EXIT

python3 - "$payload" "$MODEL" <<'PY'
import json
import sys

path, model = sys.argv[1], sys.argv[2]
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Reply with READY in one short sentence."},
    ],
    "max_tokens": 64,
    "reasoning_effort": "none",
    "stream": False,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY

echo "Probing NVIDIA build endpoint: $ENDPOINT"
echo "Model: $MODEL"

status="$(
  curl -sS \
    -o "$response" \
    -w "%{http_code}" \
    -H "Authorization: Bearer ${KEY}" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    --data-binary "@${payload}" \
    "$ENDPOINT"
)"

if [[ "$status" != 2* ]]; then
  echo "Endpoint probe failed with HTTP $status." >&2
  python3 - "$response" <<'PY' >&2
import json
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
try:
    data = json.loads(text)
    msg = data.get("error", {}).get("message") or data.get("message") or text
except Exception:
    msg = text
print(str(msg)[:800])
PY
  exit 1
fi

python3 - "$response" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
content = (
    data.get("choices", [{}])[0]
    .get("message", {})
    .get("content", "")
    .strip()
)
print("Endpoint probe succeeded.")
print(f"Model response: {content[:200]}")
PY
