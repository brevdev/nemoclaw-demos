#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 0 ]]; then
  TARGET="$1"
else
  TARGET=""
  for candidate in \
    "$HOME/.nemoclaw/source/dist/lib/onboard.js" \
    "$HOME/.nemoclaw/source/bin/lib/onboard.js"
  do
    if [[ -f "$candidate" ]]; then
      TARGET="$candidate"
      break
    fi
  done
fi

if [[ -z "$TARGET" || ! -f "$TARGET" ]]; then
  echo "Cannot find NemoClaw onboarding script." >&2
  echo "Try: find \"\$HOME\" /usr/local/lib /usr/lib -path '*nemoclaw*' -name 'onboard.js' 2>/dev/null | head -20" >&2
  exit 1
fi

if grep -q "NVIDIA Endpoints /v1/responses does not run a server-side tool-call" "$TARGET"; then
  echo "NemoClaw build-provider tool-call patch already present: $TARGET"
  exit 0
fi

python3 - "$TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
needle = 'if (selected.key === "build") {'
validation = "validateOpenAiLikeSelection"
start = text.find(needle)
while start != -1 and validation not in text[start : start + 1200]:
    start = text.find(needle, start + 1)
if start == -1:
    raise SystemExit("Could not locate build provider validation block.")

marker = 'console.log(`  Using ${remoteConfig.label} with model: ${model}`);'
pos = text.find(marker, start)
if pos == -1:
    raise SystemExit("Could not locate insertion point after build validation loop.")

line_start = text.rfind("\n", 0, pos) + 1
indent = text[line_start:pos]
insertion = f"""{indent}// NVIDIA Endpoints /v1/responses does not run a server-side tool-call
{indent}// parser for Nemotron models. Force chat completions so OpenClaw
{indent}// receives structured tool_calls instead of raw XML-style text.
{indent}// See: https://github.com/NVIDIA/NemoClaw/issues/976
{indent}if (preferredInferenceApi !== "openai-completions") {{
{indent}  console.log("  ℹ Using chat completions API (tool-call-parser requires /v1/chat/completions)");
{indent}}}
{indent}preferredInferenceApi = "openai-completions";
"""
path.write_text(text[:pos] + insertion + text[pos:])
PY

echo "Patched NemoClaw build provider to force openai-completions: $TARGET"
