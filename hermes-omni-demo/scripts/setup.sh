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

SANDBOX="${SANDBOX:-my-hermes}"
HERE=$(cd "$(dirname "$0")/.." && pwd)

echo "→ sandbox: $SANDBOX"
echo "→ source:  $HERE"
echo

# ── 1. fix the two display labels (gateway route is set separately) ──
echo "[1/5] fixing display labels"
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "sed -i 's|nvidia/nemotron-3-super-120b-a12b|nvidia/nemotron-3-nano-omni-30b-a3b-reasoning|' \
   /sandbox/.hermes-data/config.yaml" 2>/dev/null || true

python3 - <<PY
import json, pathlib
p = pathlib.Path.home() / '.nemoclaw' / 'sandboxes.json'
if p.exists():
    d = json.load(open(p))
    if "$SANDBOX" in d.get("sandboxes", {}):
        d["sandboxes"]["$SANDBOX"]["model"] = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
        json.dump(d, open(p, "w"), indent=4)
        print("    host metadata updated")
PY

# ── 2. apply the lookup policy ──
echo "[2/5] applying lookup policy (Wikipedia + Free Dictionary)"
openshell policy get "$SANDBOX" --full > /tmp/raw-policy-$$.txt
awk '/^---$/{seen=1; next} seen' /tmp/raw-policy-$$.txt > /tmp/current-policy-$$.yaml
cat "$HERE/policy/hermes-omni-lookup.yaml" >> /tmp/current-policy-$$.yaml
openshell policy set --policy /tmp/current-policy-$$.yaml "$SANDBOX" 2>&1 | grep -E "submitted|unchanged" || true
rm -f /tmp/raw-policy-$$.txt /tmp/current-policy-$$.yaml

# ── 3. install the skills ──
echo "[3/5] installing skills"
nemoclaw "$SANDBOX" skill install "$HERE/skills/video-analyze" 2>&1 | grep -E "installed|already" || true
nemoclaw "$SANDBOX" skill install "$HERE/skills/jargon-lookup" 2>&1 | grep -E "installed|already" || true

# ── 4. upload scripts ──
echo "[4/5] uploading scripts"
openshell sandbox upload "$SANDBOX" "$HERE/scripts/omni-video-analyze.py" \
  /sandbox/.hermes-data/workspace/ 2>&1 | grep -i "complete\|error" || true
openshell sandbox upload "$SANDBOX" "$HERE/scripts/lookup-jargon.py" \
  /sandbox/.hermes-data/workspace/ 2>&1 | grep -i "complete\|error" || true
openshell sandbox exec -n "$SANDBOX" -- chmod +x \
  /sandbox/.hermes-data/workspace/omni-video-analyze.py \
  /sandbox/.hermes-data/workspace/lookup-jargon.py

# ── 5. upload SOUL.md to both locations ──
echo "[5/5] uploading SOUL.md"
openshell sandbox upload "$SANDBOX" "$HERE/memories/SOUL.md" \
  /sandbox/.hermes-data/memories/ 2>&1 | grep -i "complete\|error" || true
openshell sandbox upload "$SANDBOX" "$HERE/memories/SOUL.md" \
  /sandbox/.hermes-data/ 2>&1 | grep -i "complete\|error" || true

echo
echo "✓ setup complete"
echo
echo "Next:"
echo "  bash scripts/start.sh        # build UI + run server on http://localhost:8765"
