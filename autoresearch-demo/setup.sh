#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Turn a NemoClaw + Hermes sandbox into an autonomous AI research agent.
#
# Installs:
#   1. Slurm/SSH MCP bridge (mcp-proxy + slurm-mcp on host, mcporter in sandbox)
#   2. Agent persona (SOUL.md, USER.md, MEMORY.md for autoresearch loop)
#   3. Research + MLOps skills from NousResearch/hermes-agent upstream
#
# Usage:
#   ./setup.sh --sandbox <name> --alias gpu-server=<HOST_IP> --key ~/.ssh/id_ed25519 --user <USERNAME>
#   ./setup.sh --sandbox <name>   # skills + persona only, no SSH/Slurm

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SANDBOX=""
SSH_ARGS=()
HAS_SSH=false

usage() {
  echo "Usage: $0 --sandbox <name> [SSH options]"
  echo ""
  echo "  --sandbox            OpenShell sandbox name (required)"
  echo ""
  echo "Slurm/SSH MCP options (optional — omit all to install skills only):"
  echo "  --alias <name>=<ip>  SSH alias (e.g. --alias gpu-server=<HOST_IP>)"
  echo "  --key <path>         SSH private key (stays on host, never enters sandbox)"
  echo "  --password <pass>    SSH password (use --key OR --password, not both)"
  echo "  --user <user>        SSH username"
  echo "  --user-root <path>   Remote home/root directory (default: /home/<user>)"
  echo "  --port <port>        SSH port (default: 22)"
  echo "  --mcp-port <port>    MCP proxy port on host (default: 9878)"
  echo ""
  echo "Examples:"
  echo "  $0 --sandbox research --alias gpu-server=<HOST_IP> --key ~/.ssh/id_ed25519 --user <USERNAME>"
  echo "  $0 --sandbox research   # skills + persona only"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sandbox) SANDBOX="$2"; shift 2 ;;
    --alias|--key|--password|--user|--user-root|--port|--mcp-port)
      HAS_SSH=true
      SSH_ARGS+=("$1" "$2")
      shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

[[ -z "$SANDBOX" ]] && echo "Error: --sandbox is required." && usage

if ! openshell sandbox get "$SANDBOX" &>/dev/null; then
  echo "Error: sandbox '$SANDBOX' not found or not running."
  echo "  Create it first: nemoclaw onboard"
  exit 1
fi

echo "=== Setting up AI Research Agent in sandbox '$SANDBOX' ==="
echo ""

# -- Step 1: Slurm/SSH MCP (optional) -----------------------------------------

if [[ "$HAS_SSH" == true ]]; then
  echo "--- Step 1/3: Slurm/SSH MCP ---"
  "$ROOT_DIR/bootstrap.sh" --sandbox "$SANDBOX" "${SSH_ARGS[@]}"
  echo ""
else
  echo "--- Step 1/3: Slurm/SSH MCP (skipped, no --alias provided) ---"
  echo ""
fi

# -- Step 2: Agent persona -----------------------------------------------------

echo "--- Step 2/3: Agent persona ---"

for f in SOUL.md USER.md MEMORY.md; do
  if [[ -f "$ROOT_DIR/autoresearch-skill/$f" ]]; then
    openshell sandbox upload "$SANDBOX" "$ROOT_DIR/autoresearch-skill/$f" /sandbox/.hermes-data/memories/
  fi
done
echo "  Uploaded SOUL.md, USER.md, MEMORY.md to /sandbox/.hermes-data/memories/"

# -- Step 3: Research + MLOps skills -------------------------------------------

echo "--- Step 3/3: Research & MLOps skills ---"

SKILLS_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/nemoclaw-autoresearch/hermes-skills"

echo "Fetching latest skills from NousResearch/hermes-agent..."
rm -rf "$SKILLS_CACHE"
mkdir -p "$(dirname "$SKILLS_CACHE")"
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/NousResearch/hermes-agent.git "$SKILLS_CACHE" 2>&1
cd "$SKILLS_CACHE"
git sparse-checkout set skills/research skills/mlops 2>&1
cd "$ROOT_DIR"

echo "Uploading research skills..."
openshell sandbox upload "$SANDBOX" "$SKILLS_CACHE/skills/research" /sandbox/.hermes-data/skills/research

echo "Uploading mlops skills..."
openshell sandbox upload "$SANDBOX" "$SKILLS_CACHE/skills/mlops" /sandbox/.hermes-data/skills/mlops

SKILL_COUNT=$(openshell sandbox exec -n "$SANDBOX" -- bash -c 'find /sandbox/.hermes-data/skills -name "SKILL.md" | wc -l' 2>/dev/null | tr -d ' ')
echo "  Installed: $SKILL_COUNT skills (latest from upstream)"

echo ""
echo "=== AI Research Agent ready ==="
echo ""
echo "  Sandbox: $SANDBOX"
echo "  Skills:  research (arxiv, paper-writing, literature review)"
echo "           mlops (training, inference, evaluation, vllm, huggingface)"
if [[ "$HAS_SSH" == true ]]; then
  echo "  Slurm:   configured (see Step 1 output above)"
fi
echo ""
echo "Try:"
echo '  "Check GPU availability on builder"'
echo '  "Search arxiv for recent papers on mixture of experts"'
echo '  "Set up an autoresearch loop to optimize train.py on builder"'
