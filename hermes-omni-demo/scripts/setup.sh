#!/usr/bin/env bash
# setup.sh — one-shot configuration of an already-onboarded sandbox.
#
# Run this AFTER `nemoclaw onboard --agent hermes` and AFTER you've switched
# the gateway to Omni (see Part 2 of the guide). It applies the lookup
# policy, installs the two skills, uploads the scripts and SOUL.md, and
# fixes the two display labels that still say "Super 120B".
#
# Usage:
#   SANDBOX=my-hermes bash scripts/setup.sh
#
# Defaults:
#   SANDBOX  : my-hermes (override with env var)
set -euo pipefail

# Bootstrap nvm if present so this works over non-login SSH (cron, systemd).
[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"

SANDBOX="${SANDBOX:-my-hermes}"
HERE=$(cd "$(dirname "$0")/.." && pwd)

echo "→ sandbox: $SANDBOX"
echo "→ source:  $HERE"
echo

# Verify the sandbox actually exists before doing anything destructive.
if ! nemoclaw "$SANDBOX" status >/dev/null 2>&1; then
    echo "✗ sandbox '$SANDBOX' not found." >&2
    echo "  available sandboxes:" >&2
    nemoclaw list 2>&1 | sed -n '/Sandboxes:/,/^$/p' | tail -n +2 >&2
    echo "  Set SANDBOX=<name> or run: nemoclaw onboard --agent hermes" >&2
    exit 1
fi

# Hermes config/state: current NemoClaw images use /sandbox/.hermes; older
# images used /sandbox/.hermes-data (see NemoClaw agents/hermes/manifest.yaml).
# One line: openshell rejects newlines inside exec command arguments (gRPC).
HERMES_STATE=$(openshell sandbox exec -n "$SANDBOX" -- bash -c \
  'if [ -f /sandbox/.hermes/config.yaml ]; then echo /sandbox/.hermes; elif [ -f /sandbox/.hermes-data/config.yaml ]; then echo /sandbox/.hermes-data; else echo MISSING; fi' \
  | tr -d '\r\n[:space:]')
if [[ "$HERMES_STATE" == "MISSING" ]]; then
    echo "✗ Hermes config.yaml not found under /sandbox/.hermes or /sandbox/.hermes-data." >&2
    exit 1
fi

# ── 1. fix the two display labels (gateway route is set separately) ──
echo "[1/5] fixing display labels"
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "sed -i 's|nvidia/nemotron-3-super-120b-a12b|nvidia/nemotron-3-nano-omni-30b-a3b-reasoning|' ${HERMES_STATE}/config.yaml"

# Long-video skill can take 5-10 minutes on a 2hr+ recording (audio
# transcription is multiple pieces). Hermes's default terminal-tool
# timeout (180s) kills it with exit 124. Bump to 30 min so the skill
# has room to finish.
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "sed -i 's|^  timeout: 180$|  timeout: 1800|' ${HERMES_STATE}/config.yaml"

python3 - "$SANDBOX" <<'PY'
import json, pathlib, sys
sandbox = sys.argv[1]
p = pathlib.Path.home() / '.nemoclaw' / 'sandboxes.json'
if not p.exists():
    print(f"    note: {p} not found — skipping host metadata update")
    sys.exit(0)
d = json.load(open(p))
sandboxes = d.get("sandboxes", {})
if sandbox not in sandboxes:
    print(f"    warning: {sandbox!r} not in {p}; available: {sorted(sandboxes)}")
    sys.exit(0)
sandboxes[sandbox]["model"] = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
json.dump(d, open(p, "w"), indent=4)
print("    host metadata updated")
PY

# ── 2. apply the lookup policy ──
echo "[2/5] applying lookup policy (Wikipedia + Free Dictionary)"
raw_policy=$(mktemp)
current_policy=$(mktemp)
trap 'rm -f "$raw_policy" "$current_policy"' EXIT

openshell policy get "$SANDBOX" --full > "$raw_policy"
awk '/^---$/{seen=1; next} seen' "$raw_policy" > "$current_policy"
cat "$HERE/policy/hermes-omni-lookup.yaml" >> "$current_policy"
openshell policy set --policy "$current_policy" "$SANDBOX"

# ── 3. install the skills ──
echo "[3/5] installing skills"
nemoclaw "$SANDBOX" skill install "$HERE/skills/video-analyze"
nemoclaw "$SANDBOX" skill install "$HERE/skills/jargon-lookup"

# ── 4. upload scripts ──
echo "[4/5] uploading scripts"
openshell sandbox upload "$SANDBOX" "$HERE/scripts/omni-video-analyze.py" \
  "${HERMES_STATE}/workspace/"
openshell sandbox upload "$SANDBOX" "$HERE/scripts/lookup-jargon.py" \
  "${HERMES_STATE}/workspace/"
openshell sandbox exec -n "$SANDBOX" -- chmod +x \
  "${HERMES_STATE}/workspace/omni-video-analyze.py" \
  "${HERMES_STATE}/workspace/lookup-jargon.py"

# ── 5. upload SOUL.md to both locations ──
# Canonical copy under memories/; also at Hermes home root where some images
# keep SOUL.md for the agent entrypoint.
echo "[5/5] uploading SOUL.md"
openshell sandbox upload "$SANDBOX" "$HERE/memories/SOUL.md" \
  "${HERMES_STATE}/memories/"
openshell sandbox upload "$SANDBOX" "$HERE/memories/SOUL.md" \
  "${HERMES_STATE}/"

# ── 6. verify the SOUL.md is readable through the path Hermes uses ──
expected=$(wc -c < "$HERE/memories/SOUL.md")
actual=$(openshell sandbox exec -n "$SANDBOX" -- bash -c \
    "wc -c </sandbox/.hermes/SOUL.md 2>/dev/null || wc -c <${HERMES_STATE}/SOUL.md 2>/dev/null || wc -c <${HERMES_STATE}/memories/SOUL.md" \
    | tr -d '[:space:]')
if [[ "$actual" != "$expected" ]]; then
    echo "✗ SOUL.md verification failed: expected $expected bytes, got $actual" >&2
    echo "  Hermes will not see the demo's tool instructions." >&2
    exit 1
fi
echo "    verified SOUL.md visible to Hermes ($expected bytes)"

echo
echo "✓ setup complete"
echo
echo "Next:"
echo "  bash scripts/start.sh        # build UI + run server on http://localhost:8765"
