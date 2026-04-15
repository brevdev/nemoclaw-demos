#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
MCP_PORT=9000
TMUX_SESSION="slurm-mcp"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  Slurm MCP Demo Installer for NemoClaw                  ║${NC}"
echo -e "${CYAN}  ║  Fake HPC Cluster via MCP + OpenClaw Skill              ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Clean up stale environment ───────────────────────────
info "Cleaning up stale environment..."
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  tmux kill-session -t "$TMUX_SESSION"
  ok "Killed existing tmux session '$TMUX_SESSION'"
fi
STALE=$(pgrep -f "fake_cluster_mcp_server" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  kill $STALE 2>/dev/null || true
  ok "Killed stale MCP server process(es)"
fi
ok "Environment clean"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────────
info "Checking prerequisites..."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found. Is NemoClaw installed?"
command -v nemoclaw  >/dev/null 2>&1 || fail "nemoclaw CLI not found. Is NemoClaw installed?"
command -v python3   >/dev/null 2>&1 || fail "python3 not found."

if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv install failed. Add ~/.local/bin to PATH and retry."
  ok "uv installed"
fi
ok "Prerequisites OK"
echo ""

# ── Step 2: Load .env and resolve inference config ───────────────
info "Loading configuration..."

# Load .env if present (values do NOT override existing env vars)
if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and blank lines
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    # Strip surrounding quotes from value
    val="${val#\"}" ; val="${val%\"}" ; val="${val#\'}" ; val="${val%\'}"
    # Only set if not already in environment
    [ -z "${!key+x}" ] && export "$key"="$val"
  done < "$SCRIPT_DIR/.env"
  ok "Loaded .env from $SCRIPT_DIR/.env"
fi

# Fall back to credentials.json for INFERENCE_API_KEY
if [ -z "${INFERENCE_API_KEY:-}" ] && [ -f "$CREDS_PATH" ]; then
  INFERENCE_API_KEY=$(python3 -c "
import json
print(json.load(open('$CREDS_PATH')).get('INFERENCE_API_KEY',''))
" 2>/dev/null || true)
  [ -n "${INFERENCE_API_KEY:-}" ] && ok "INFERENCE_API_KEY loaded from $CREDS_PATH"
fi

[ -z "${INFERENCE_API_KEY:-}" ] && fail "INFERENCE_API_KEY is not set. Add it to $SCRIPT_DIR/.env or run: export INFERENCE_API_KEY=<your-key>"

# Apply defaults for optional config vars
INFERENCE_PROVIDER_TYPE="${INFERENCE_PROVIDER_TYPE:-nvidia}"
INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-nvidia}"
INFERENCE_BASE_URL="${INFERENCE_BASE_URL:-https://inference-api.nvidia.com/v1}"
INFERENCE_MODEL="${INFERENCE_MODEL:-aws/anthropic/bedrock-claude-opus-4-6}"

ok "INFERENCE_API_KEY   : found"
ok "INFERENCE_PROVIDER  : $INFERENCE_PROVIDER_NAME (type=$INFERENCE_PROVIDER_TYPE)"
ok "INFERENCE_BASE_URL  : $INFERENCE_BASE_URL"
ok "INFERENCE_MODEL     : $INFERENCE_MODEL"
echo ""

# ── Step 3: Onboard if no sandbox exists ─────────────────────────
# Count sandboxes that are actually live (not just entries in sandboxes.json)
live_sandboxes() {
  openshell sandbox list 2>/dev/null | grep -v "^No sandboxes" | grep -v "^NAME" | awk '{print $1}' | grep -v '^$' || true
}

LIVE_COUNT=$(live_sandboxes | wc -l | tr -d ' ')

if [ "${LIVE_COUNT:-0}" -eq 0 ]; then
  info "Configuring inference provider '$INFERENCE_PROVIDER_NAME' and model..."
  openshell provider create \
    --type "$INFERENCE_PROVIDER_TYPE" \
    --name "$INFERENCE_PROVIDER_NAME" \
    --credential INFERENCE_API_KEY \
    --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL" \
    2>/dev/null && ok "Provider '$INFERENCE_PROVIDER_NAME' created" \
    || warn "Provider '$INFERENCE_PROVIDER_NAME' already exists — continuing"
  openshell inference set \
    --provider "$INFERENCE_PROVIDER_NAME" \
    --model "$INFERENCE_MODEL"
  ok "Inference set to $INFERENCE_MODEL via $INFERENCE_PROVIDER_NAME"
  echo ""

  echo -e "  ${YELLOW}No sandbox found — running 'nemoclaw onboard'...${NC}"
  echo -e "  ${YELLOW}Provider and model are pre-configured — you only need to confirm the sandbox name.${NC}"
  echo ""
  # NOTE: no --yes-i-accept-third-party-software — consent is required interactively
  nemoclaw onboard
  echo ""
  ok "Onboarding complete"
  echo ""

  # Wait up to 20 s for the new sandbox to appear in the live list
  info "Waiting for sandbox to become ready..."
  for i in $(seq 1 20); do
    LIVE_COUNT=$(live_sandboxes | wc -l | tr -d ' ')
    [ "${LIVE_COUNT:-0}" -gt 0 ] && break
    sleep 1
  done
  [ "${LIVE_COUNT:-0}" -eq 0 ] && fail "No sandbox appeared after onboarding. Run 'openshell sandbox list' to check."
fi

# ── Step 4: Resolve sandbox name ─────────────────────────────────
# Priority: CLI arg → only live sandbox → sandboxes.json default (validated) → prompt

if [ -n "${1:-}" ]; then
  SANDBOX_NAME="$1"
else
  LIVE_NAMES=$(live_sandboxes)
  LIVE_COUNT=$(echo "$LIVE_NAMES" | grep -c . || true)

  if [ "${LIVE_COUNT:-0}" -eq 1 ]; then
    # Exactly one live sandbox — use it regardless of sandboxes.json
    SANDBOX_NAME=$(echo "$LIVE_NAMES" | head -1)

  else
    # Multiple live sandboxes — try sandboxes.json default, but validate it is actually live
    JSON_DEFAULT=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox') or '')
except: pass
" 2>/dev/null || true)

    if [ -n "${JSON_DEFAULT:-}" ] && echo "$LIVE_NAMES" | grep -qx "$JSON_DEFAULT"; then
      SANDBOX_NAME="$JSON_DEFAULT"
    else
      # sandboxes.json default is stale or absent — ask the user
      echo ""
      echo -e "  ${YELLOW}Multiple sandboxes found:${NC}"
      echo "$LIVE_NAMES" | while read -r n; do echo "    - $n"; done
      echo ""
      echo -n "  Which sandbox should be used? "
      read -r SANDBOX_NAME
    fi
  fi
fi

[ -z "${SANDBOX_NAME:-}" ] && fail "Could not determine sandbox name. Usage: ./install.sh <sandbox-name>"

# Final check: confirm the chosen name is actually live
if ! live_sandboxes | grep -qx "$SANDBOX_NAME"; then
  echo ""
  echo -e "  ${RED}  ✗ Sandbox '$SANDBOX_NAME' not found. Live sandboxes:${NC}"
  live_sandboxes | while read -r n; do echo "    - $n"; done
  echo ""
  fail "Re-run with: bash install.sh <sandbox-name>"
fi

info "Target sandbox: $SANDBOX_NAME"
echo ""

# Persist key in credentials.json (mode 600)
mkdir -p "$(dirname "$CREDS_PATH")"
python3 -c "
import json, os
path = '$CREDS_PATH'
try: d = json.load(open(path))
except: d = {}
d['INFERENCE_API_KEY'] = '$INFERENCE_API_KEY'
d['INFERENCE_PROVIDER_TYPE'] = '$INFERENCE_PROVIDER_TYPE'
d['INFERENCE_PROVIDER_NAME'] = '$INFERENCE_PROVIDER_NAME'
d['INFERENCE_BASE_URL'] = '$INFERENCE_BASE_URL'
d['INFERENCE_MODEL'] = '$INFERENCE_MODEL'
with open(path, 'w') as f: json.dump(d, f, indent=2)
os.chmod(path, 0o600)
" 2>/dev/null || true

# ── Step 5: Install Python dependencies ─────────────────────────
info "Installing Python dependencies (latest versions)..."
cd "$SCRIPT_DIR"
uv venv --quiet
uv pip install --quiet --upgrade \
  fastmcp \
  colorama
ok "Dependencies installed in .venv"
echo ""

# ── Step 6: Start MCP server in tmux ────────────────────────────
info "Starting MCP server in tmux session '$TMUX_SESSION'..."

tmux new-session -d -s "$TMUX_SESSION" \
  "cd '$SCRIPT_DIR' && \
   source .venv/bin/activate && \
   python fake_cluster_mcp_server.py --port $MCP_PORT 2>&1 | tee /tmp/slurm-mcp.log"

# Wait up to 10 s for the port to open
SERVER_UP=false
for i in $(seq 1 10); do
  sleep 1
  if curl -s --max-time 1 "http://127.0.0.1:${MCP_PORT}/mcp" >/dev/null 2>&1; then
    SERVER_UP=true
    break
  fi
done

tmux has-session -t "$TMUX_SESSION" 2>/dev/null \
  || fail "tmux session died immediately. Check /tmp/slurm-mcp.log"

if [ "$SERVER_UP" = true ]; then
  ok "MCP server is up on port $MCP_PORT"
else
  warn "MCP server not responding yet — check: tmux attach -t $TMUX_SESSION"
fi
echo ""

# ── Step 7: Apply sandbox network policy ────────────────────────
info "Applying sandbox network policy..."
openshell policy set "$SANDBOX_NAME" \
  --policy "$SCRIPT_DIR/sandbox_policy.yaml" \
  --wait
ok "Policy applied"
echo ""

# ── Step 8: Upload slurm-cluster-mcp skill ──────────────────────
info "Uploading slurm-cluster-mcp skill to sandbox..."
openshell sandbox upload "$SANDBOX_NAME" \
  "$SCRIPT_DIR/slurm-cluster-mcp" \
  /sandbox/.openclaw/workspace/skills/slurm-cluster-mcp
ok "Skill uploaded to /sandbox/.openclaw/workspace/skills/slurm-cluster-mcp/"
echo ""

# ── Step 8b: Bootstrap skill venv with required deps ────────────
# The agent runs mcp_client.py via this venv — it must be in the policy's
# allowed binaries (sandbox_policy.yaml covers /sandbox/.openclaw/workspace/skills/*/venv/bin/*)
info "Setting up skill Python venv (fastmcp + deps)..."
SKILL_VENV=/sandbox/.openclaw/workspace/skills/slurm-cluster-mcp/venv
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  python3 -m venv "$SKILL_VENV" \
  || fail "Failed to create skill venv at $SKILL_VENV inside sandbox '$SANDBOX_NAME'."
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/pip" install -q fastmcp colorama python-dotenv \
  || fail "pip install failed inside the skill venv. Check sandbox connectivity."
VENV_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import fastmcp, colorama; print('ok')" 2>/dev/null || true)
[ "$VENV_CHECK" = "ok" ] \
  && ok "Skill venv ready ($SKILL_VENV)" \
  || fail "Skill venv verification failed — 'import fastmcp, colorama' returned no output. Re-run install.sh."
echo ""

# ── Step 8c: Restart the OpenClaw gateway so it sees the new venv ─
info "Restarting OpenClaw gateway in sandbox '$SANDBOX_NAME'..."
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  openclaw gateway restart 2>/dev/null \
  || openshell sandbox exec -n "$SANDBOX_NAME" -- \
     sh -c "openclaw gateway stop 2>/dev/null; sleep 1; openclaw gateway start" \
  || warn "Could not restart OpenClaw gateway — you may need to reconnect manually."
ok "Gateway restarted"
echo ""

# ── Step 9: Verify ───────────────────────────────────────────────
info "Verifying installation..."

MCP_UP=$(curl -s --max-time 3 "http://127.0.0.1:${MCP_PORT}/mcp" 2>&1 | wc -c || true)
[ "${MCP_UP:-0}" -gt 0 ] \
  && ok "MCP server responding on http://127.0.0.1:${MCP_PORT}/mcp" \
  || warn "MCP server not responding — check: tmux attach -t $TMUX_SESSION"

SKILL_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f /sandbox/.openclaw/workspace/skills/slurm-cluster-mcp/SKILL.md && echo ok" \
  2>/dev/null || true)
[ "$SKILL_CHECK" = "ok" ] \
  && ok "Skill confirmed in sandbox" \
  || warn "Skill not yet visible in sandbox — try reconnecting"

FASTMCP_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import fastmcp, colorama; print('ok')" \
  2>/dev/null || true)
[ "$FASTMCP_CHECK" = "ok" ] \
  && ok "fastmcp + colorama reachable via skill venv" \
  || warn "skill venv import check failed — try re-running install.sh"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  MCP server : http://127.0.0.1:${MCP_PORT}/mcp  (tmux: $TMUX_SESSION)"
echo "  Sandbox URL: http://host.openshell.internal:${MCP_PORT}/mcp"
echo "  Server logs: tmux attach -t $TMUX_SESSION  (Ctrl-B D to detach)"
echo ""
echo "  Next steps:"
echo "    1. Connect:  nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"What GPU partitions are available on the cluster?\""
echo "    3. Try: \"Launch a training job with 4 GPUs for 10 epochs using vit-large\""
echo "    4. Try: \"Show me what jobs are currently running\""
echo "    5. Try: \"How much compute have I used this month?\""
echo ""
echo "  If the agent doesn't find the skill, disconnect and reconnect."
echo -e "  ${YELLOW}To restart: tmux kill-session -t $TMUX_SESSION && bash $SCRIPT_DIR/install.sh $SANDBOX_NAME${NC}"
echo ""
