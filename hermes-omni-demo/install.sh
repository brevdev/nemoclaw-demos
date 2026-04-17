#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# One-shot installer for the NemoClaw + Hermes + Omni cookbook.
# After `nemoclaw onboard --agent hermes` creates your sandbox, this script:
#   1. Applies the wikipedia + free_dictionary policy preset
#   2. Installs the video-analyze and jargon-lookup skills
#   3. Uploads the scripts to the sandbox workspace
#   4. Drops SOUL.md into the Hermes memories directory
#
# Usage:
#   export SANDBOX=my-hermes             # whatever you named it during onboard
#   ./install.sh

set -euo pipefail

SANDBOX="${SANDBOX:-${1:-}}"
if [[ -z "$SANDBOX" ]]; then
  echo "Error: set SANDBOX=<sandbox-name> or pass it as the first argument." >&2
  echo "Example: SANDBOX=my-hermes ./install.sh" >&2
  exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "==> Installing Hermes + Omni cookbook into sandbox: $SANDBOX"

# ── Part 1/4: Apply the policy preset ───────────────────────────
echo "[1/4] Applying wikipedia + free_dictionary policy preset..."
openshell policy set --policy policy/hermes-omni-lookup.yaml "$SANDBOX"

# ── Part 2/4: Install skills ────────────────────────────────────
echo "[2/4] Installing skills (video-analyze, jargon-lookup)..."
nemoclaw "$SANDBOX" skill install "skills/video-analyze"
nemoclaw "$SANDBOX" skill install "skills/jargon-lookup"

# ── Part 3/4: Upload scripts to workspace ───────────────────────
echo "[3/4] Uploading scripts to sandbox workspace..."
openshell sandbox upload "$SANDBOX" scripts/omni-video-analyze.py /sandbox/.hermes-data/workspace/
openshell sandbox upload "$SANDBOX" scripts/lookup-jargon.py /sandbox/.hermes-data/workspace/

# openshell upload puts files inside a DEST dir of the same name. Flatten them
# out and make them executable.
openshell sandbox exec -n "$SANDBOX" -- bash -c '
  WORK=/sandbox/.hermes-data/workspace
  for f in omni-video-analyze.py lookup-jargon.py; do
    if [[ -d "$WORK/$f" ]]; then
      mv "$WORK/$f/$f" "$WORK/$f.tmp"
      rmdir "$WORK/$f"
      mv "$WORK/$f.tmp" "$WORK/$f"
    fi
    chmod +x "$WORK/$f"
  done
  ls -la "$WORK"
'

# ── Part 4/4: Drop SOUL.md ──────────────────────────────────────
echo "[4/4] Installing SOUL.md..."
openshell sandbox upload "$SANDBOX" memories/SOUL.md /sandbox/.hermes-data/memories/
# Also install at the root path — Hermes loads both and a stale one will override.
openshell sandbox upload "$SANDBOX" memories/SOUL.md /sandbox/.hermes-data/
openshell sandbox exec -n "$SANDBOX" -- bash -c '
  for dir in /sandbox/.hermes-data/memories /sandbox/.hermes-data; do
    if [[ -d "$dir/SOUL.md" ]]; then
      mv "$dir/SOUL.md/SOUL.md" "$dir/SOUL.md.tmp"
      rmdir "$dir/SOUL.md"
      mv "$dir/SOUL.md.tmp" "$dir/SOUL.md"
    fi
  done
  ls -la /sandbox/.hermes-data/SOUL.md /sandbox/.hermes-data/memories/SOUL.md
'

echo
echo "==> Install complete."
echo
echo "Next: connect to the sandbox and start chatting:"
echo "  nemoclaw $SANDBOX connect"
echo "  hermes chat"
echo
echo "Then try:"
echo '  Analyze /tmp/test-video.mp4 and tell me what is happening.'
