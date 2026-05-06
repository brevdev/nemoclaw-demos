#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
MCP_PORT=9001
TMUX_SESSION="alfworld-mcp"
MCP_LOG_FILE="/tmp/alfworld-mcp.log"

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
echo -e "${CYAN}  ║  ALFWorld Visual Game MCP Demo Installer for NemoClaw   ║${NC}"
echo -e "${CYAN}  ║  AI2-THOR 3D Environment via MCP + OpenClaw Skill       ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Clean up stale environment ───────────────────────────
info "Cleaning up stale environment..."
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  tmux kill-session -t "$TMUX_SESSION"
  ok "Killed existing tmux session '$TMUX_SESSION'"
fi
STALE=$(pgrep -f "alfworld_env_mcp_server_visual" 2>/dev/null || true)
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

# AI2-THOR requires OpenGL and X11 libraries for headless rendering.
# Check for the key library and install the full set only if absent.
if ! ldconfig -p 2>/dev/null | grep -q "libGL.so"; then
  warn "OpenGL/X11 libraries not found — installing system dependencies..."
  sudo apt-get update -qq
  sudo apt-get install -y -qq \
    xvfb \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    || fail "apt-get install failed. Run with sudo or install the packages manually."
  ok "System OpenGL/X11 libraries installed"
else
  ok "OpenGL/X11 libraries already present"
fi

command -v Xvfb >/dev/null 2>&1 || fail "Xvfb not found after apt install. Try: sudo apt-get install -y xvfb"
ok "Prerequisites OK"
echo ""

# ── Step 2: Load .env and resolve inference config ───────────────
info "Loading configuration..."

# Load .env if present (values do NOT override existing env vars).
# The user fills in .env with real keys before running this script.
if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    val="${val#\"}" ; val="${val%\"}" ; val="${val#\'}" ; val="${val%\'}"
    [ -z "${!key+x}" ] && export "$key"="$val"
  done < "$SCRIPT_DIR/.env"
  ok "Loaded .env from $SCRIPT_DIR/.env"
else
  warn ".env not found at $SCRIPT_DIR/.env"
  warn "Copy .env.template to .env and fill in your keys, then re-run."
  echo ""
  fail "Missing .env — see README for setup instructions."
fi

# Fall back to credentials.json for INFERENCE_API_KEY
if [ -z "${INFERENCE_API_KEY:-}" ] && [ -f "$CREDS_PATH" ]; then
  INFERENCE_API_KEY=$(python3 -c "
import json
print(json.load(open('$CREDS_PATH')).get('INFERENCE_API_KEY',''))
" 2>/dev/null || true)
  [ -n "${INFERENCE_API_KEY:-}" ] && ok "INFERENCE_API_KEY loaded from $CREDS_PATH"
fi

[ -z "${INFERENCE_API_KEY:-}" ] && fail "INFERENCE_API_KEY is not set. Add it to $SCRIPT_DIR/.env"

# Apply defaults for optional inference config vars
INFERENCE_PROVIDER_TYPE="${INFERENCE_PROVIDER_TYPE:-nvidia}"
INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-nvidia}"
INFERENCE_BASE_URL="${INFERENCE_BASE_URL:-https://inference-api.nvidia.com/v1}"
INFERENCE_MODEL="${INFERENCE_MODEL:-aws/anthropic/bedrock-claude-opus-4-6}"

# ALFWorld data path — required
ALFWORLD_DATA="${ALFWORLD_DATA:-/ephemeral/cache/alfworld}"
MCP_PORT="${MCP_ALFWORLD_PORT:-$MCP_PORT}"

ok "INFERENCE_API_KEY   : found"
ok "INFERENCE_PROVIDER  : $INFERENCE_PROVIDER_NAME (type=$INFERENCE_PROVIDER_TYPE)"
ok "INFERENCE_BASE_URL  : $INFERENCE_BASE_URL"
ok "INFERENCE_MODEL     : $INFERENCE_MODEL"
ok "ALFWORLD_DATA       : $ALFWORLD_DATA"
ok "MCP_PORT            : $MCP_PORT"

# Validate that ALFWORLD_DATA exists and looks like a real dataset
NEED_ALFWORLD_DOWNLOAD=false
if [ ! -d "$ALFWORLD_DATA" ]; then
  warn "ALFWORLD_DATA directory not found: $ALFWORLD_DATA"
  warn "Data will be downloaded automatically after the Python venv is set up."
  NEED_ALFWORLD_DOWNLOAD=true
elif [ ! -d "$ALFWORLD_DATA/json_2.1.1" ]; then
  warn "Expected subdirectory 'json_2.1.1' not found under $ALFWORLD_DATA"
  warn "Data appears incomplete — will re-download."
  NEED_ALFWORLD_DOWNLOAD=true
else
  ok "ALFWORLD_DATA validated: $ALFWORLD_DATA"
fi
echo ""

# ── Step 3: Onboard if no sandbox exists ─────────────────────────
live_sandboxes() {
  openshell sandbox list 2>/dev/null | grep -v "^No sandboxes" | grep -v "^NAME" | awk '{print $1}' | grep -v '^$' || true
}

LIVE_COUNT=$(live_sandboxes | wc -l | tr -d ' ')

if [ "${LIVE_COUNT:-0}" -eq 0 ]; then
  echo -e "  ${YELLOW}No sandbox found — running 'nemoclaw onboard'...${NC}"
  echo ""
  nemoclaw onboard
  echo ""
  ok "Onboarding complete"
  echo ""

  info "Waiting for sandbox to become ready..."
  for i in $(seq 1 20); do
    LIVE_COUNT=$(live_sandboxes | wc -l | tr -d ' ')
    [ "${LIVE_COUNT:-0}" -gt 0 ] && break
    sleep 1
  done
  [ "${LIVE_COUNT:-0}" -eq 0 ] && fail "No sandbox appeared after onboarding. Run 'openshell sandbox list' to check."
fi

# Enforce correct provider + inference model (idempotent — runs every time)
info "Ensuring inference provider '$INFERENCE_PROVIDER_NAME' (${INFERENCE_BASE_URL})..."
openshell provider create \
  --type "$INFERENCE_PROVIDER_TYPE" \
  --name "$INFERENCE_PROVIDER_NAME" \
  --credential INFERENCE_API_KEY \
  --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL" \
  2>/dev/null \
  && ok "Provider '$INFERENCE_PROVIDER_NAME' created" \
  || ok "Provider '$INFERENCE_PROVIDER_NAME' already exists"

info "Setting inference model to $INFERENCE_MODEL..."
openshell inference set \
  --provider "$INFERENCE_PROVIDER_NAME" \
  --model "$INFERENCE_MODEL" \
  && ok "Inference set: $INFERENCE_PROVIDER_NAME / $INFERENCE_MODEL" \
  || fail "Could not set inference model. Run manually: openshell inference set --provider $INFERENCE_PROVIDER_NAME --model $INFERENCE_MODEL"
echo ""

# ── Step 4: Resolve sandbox name ─────────────────────────────────
if [ -n "${1:-}" ]; then
  SANDBOX_NAME="$1"
else
  LIVE_NAMES=$(live_sandboxes)
  LIVE_COUNT=$(echo "$LIVE_NAMES" | grep -c . || true)

  if [ "${LIVE_COUNT:-0}" -eq 1 ]; then
    SANDBOX_NAME=$(echo "$LIVE_NAMES" | head -1)
  else
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

if ! live_sandboxes | grep -qx "$SANDBOX_NAME"; then
  echo ""
  echo -e "  ${RED}  ✗ Sandbox '$SANDBOX_NAME' not found. Live sandboxes:${NC}"
  live_sandboxes | while read -r n; do echo "    - $n"; done
  echo ""
  fail "Re-run with: bash install.sh <sandbox-name>"
fi

info "Target sandbox: $SANDBOX_NAME"
echo ""

# Persist inference config in credentials.json (mode 600)
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

# ── Step 5: Install host Python dependencies ─────────────────────
info "Installing Python dependencies for MCP server (host)..."
info "This includes alfworld[vis] (ai2thor, cv2, torch) — may take several minutes..."
cd "$SCRIPT_DIR"
uv venv --python 3.10 --quiet
# Force install into the venv (not ~/.local) to avoid import errors at runtime
# Python 3.10 is required — alfworld/ai2thor use ast.Str which was removed in 3.12
uv pip install --quiet --upgrade \
  fastmcp \
  colorama \
  python-dotenv \
  "alfworld[vis]"
ok "Dependencies installed in .venv"

# Verify the critical visual imports work inside the venv
IMPORT_CHECK=$(.venv/bin/python3 -c "
from ai2thor.controller import Controller
import cv2
from alfworld.agents.environment import get_environment
print('ok')
" 2>/dev/null || true)
if [ "$IMPORT_CHECK" = "ok" ]; then
  ok "Visual import check passed (ai2thor, cv2, alfworld)"
else
  warn "Visual import check failed — the venv may need a manual fix:"
  warn "  rm -rf $SCRIPT_DIR/.venv"
  warn "  uv venv --python 3.10 && uv pip install --no-user 'alfworld[vis]'"
  warn "Continuing — the server may still work if the packages are importable."
fi
echo ""

# ── Step 5b: Download ALFWorld data if needed ────────────────────
if [ "${NEED_ALFWORLD_DOWNLOAD:-false}" = "true" ]; then
  info "Downloading ALFWorld game data to $ALFWORLD_DATA ..."
  info "This is a one-time download (~1-2 GB). Please be patient."
  # Try to create the directory; fall back to ~/alfworld_data if permission denied
  if ! mkdir -p "$ALFWORLD_DATA" 2>/dev/null; then
    warn "Cannot create $ALFWORLD_DATA (permission denied)."
    ALFWORLD_DATA="$HOME/alfworld_data"
    warn "Falling back to $ALFWORLD_DATA"
    mkdir -p "$ALFWORLD_DATA"
    warn "Update ALFWORLD_DATA=$ALFWORLD_DATA in your .env to make this permanent."
  fi
  # alfworld-download reads ALFWORLD_DATA from the environment
  export ALFWORLD_DATA
  if .venv/bin/alfworld-download; then
    ok "ALFWorld data downloaded to $ALFWORLD_DATA"
    # Confirm the key subdirectory appeared
    if [ -d "$ALFWORLD_DATA/json_2.1.1" ]; then
      ok "Dataset validated (json_2.1.1 present)"
    else
      warn "Download finished but 'json_2.1.1' still not found."
      warn "Check $ALFWORLD_DATA manually before starting the server."
    fi
  else
    echo ""
    warn "alfworld-download exited with an error."
    warn "You can retry manually:"
    warn "  export ALFWORLD_DATA=$ALFWORLD_DATA"
    warn "  $SCRIPT_DIR/.venv/bin/alfworld-download"
    warn "Continuing — set a valid ALFWORLD_DATA in .env and re-run install.sh."
  fi
  echo ""
fi

# ── Step 6: Start Xvfb virtual display ───────────────────────────
info "Checking virtual display (Xvfb :1)..."
if pgrep -f "Xvfb :1" >/dev/null 2>&1; then
  ok "Xvfb :1 already running"
else
  info "Starting Xvfb :1 -screen 0 1024x768x24 ..."
  Xvfb :1 -screen 0 1024x768x24 &
  sleep 2
  if pgrep -f "Xvfb :1" >/dev/null 2>&1; then
    ok "Xvfb :1 started"
  else
    fail "Xvfb failed to start. Try manually: Xvfb :1 -screen 0 1024x768x24 &"
  fi
fi
# Confirm the X11 socket exists
if [ -S /tmp/.X11-unix/X1 ]; then
  ok "X11 socket /tmp/.X11-unix/X1 confirmed"
else
  warn "X11 socket /tmp/.X11-unix/X1 not found — AI2-THOR may fail to render"
fi
export DISPLAY=:1
echo ""

# ── Step 7: Start MCP server in tmux ────────────────────────────
info "Starting ALFWorld MCP server in tmux session '$TMUX_SESSION'..."
info "Note: on first run AI2-THOR downloads its Unity binary (~390 MB)."
info "      The server will be slow to respond until the download completes."

tmux new-session -d -s "$TMUX_SESSION" \
  "cd '$SCRIPT_DIR' && \
   export DISPLAY=:1 && \
   export ALFWORLD_DATA='$ALFWORLD_DATA' && \
   export MCP_ALFWORLD_PORT='$MCP_PORT' && \
   source .venv/bin/activate && \
   python alfworld_env_mcp_server_visual.py --port '$MCP_PORT' 2>&1 | tee '$MCP_LOG_FILE'"

ok "tmux session '$TMUX_SESSION' launched"

# Wait up to 90 s — first run needs to download the AI2-THOR binary (~390 MB)
info "Waiting for server to respond on port $MCP_PORT (up to 90 s)..."
SERVER_UP=false
for i in $(seq 1 90); do
  sleep 1
  if curl -s --max-time 1 "http://127.0.0.1:${MCP_PORT}/mcp" >/dev/null 2>&1; then
    SERVER_UP=true
    ok "MCP server is up on port $MCP_PORT (after ${i}s)"
    break
  fi
  # Print a dot every 10 s so the user can see progress
  [ $((i % 10)) -eq 0 ] && echo -e "${CYAN}  ... still waiting (${i}s)${NC}"
done

if [ "$SERVER_UP" = false ]; then
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    warn "Server not responding after 90s — but tmux session is alive."
    warn "This is normal on first run while AI2-THOR binary downloads."
    warn "Check progress: tmux attach -t $TMUX_SESSION  (Ctrl-B D to detach)"
    warn "Or watch log:   tail -f $MCP_LOG_FILE"
  else
    fail "tmux session died immediately. Check: cat $MCP_LOG_FILE"
  fi
fi
echo ""

# ── Step 8: Apply sandbox network policy ────────────────────────
info "Applying sandbox network policy..."
openshell policy set "$SANDBOX_NAME" \
  --policy "$SCRIPT_DIR/policy/sandbox_policy.yaml" \
  --wait
ok "Policy applied"
echo ""

# ── Step 9: Upload alfworld-game-viz skill ───────────────────────
info "Uploading alfworld-game-viz skill to sandbox..."
openshell sandbox upload "$SANDBOX_NAME" \
  "$SCRIPT_DIR/sandbox_alfword_viz_skills" \
  /sandbox/.openclaw/workspace/skills/alfworld-game-viz
ok "Skill uploaded to /sandbox/.openclaw/workspace/skills/alfworld-game-viz/"
echo ""

# ── Step 9b: Bootstrap skill venv with required deps ────────────
info "Setting up skill Python venv (fastmcp + colorama)..."
SKILL_VENV=/sandbox/.openclaw/workspace/skills/alfworld-game-viz/venv
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  python3 -m venv "$SKILL_VENV" \
  || fail "Failed to create skill venv at $SKILL_VENV inside sandbox '$SANDBOX_NAME'."
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/pip" install -q fastmcp colorama \
  || fail "pip install failed inside the skill venv. Check sandbox connectivity."
VENV_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import fastmcp, colorama; print('ok')" 2>/dev/null || true)
[ "$VENV_CHECK" = "ok" ] \
  && ok "Skill venv ready ($SKILL_VENV)" \
  || fail "Skill venv verification failed — 'import fastmcp, colorama' returned no output. Re-run install.sh."
echo ""

# ── Step 9c: Restart the OpenClaw gateway ───────────────────────
info "Restarting OpenClaw gateway in sandbox '$SANDBOX_NAME'..."
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  openclaw gateway restart 2>/dev/null \
  || openshell sandbox exec -n "$SANDBOX_NAME" -- \
     sh -c "openclaw gateway stop 2>/dev/null; sleep 1; openclaw gateway start" \
  || warn "Could not restart OpenClaw gateway — you may need to reconnect manually."
ok "Gateway restarted"
echo ""

# ── Step 10: Verify ──────────────────────────────────────────────
info "Verifying installation..."

MCP_UP=$(curl -s --max-time 3 "http://127.0.0.1:${MCP_PORT}/mcp" 2>&1 | wc -c || true)
[ "${MCP_UP:-0}" -gt 0 ] \
  && ok "MCP server responding on http://127.0.0.1:${MCP_PORT}/mcp" \
  || warn "MCP server not responding yet — check: tmux attach -t $TMUX_SESSION"

SKILL_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f /sandbox/.openclaw/workspace/skills/alfworld-game-viz/SKILL.md && echo ok" \
  2>/dev/null || true)
[ "$SKILL_CHECK" = "ok" ] \
  && ok "Skill confirmed in sandbox" \
  || warn "Skill not yet visible in sandbox — try reconnecting"

FASTMCP_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import fastmcp, colorama; print('ok')" \
  2>/dev/null || true)
[ "$FASTMCP_CHECK" = "ok" ] \
  && ok "fastmcp + colorama reachable via skill venv" \
  || warn "Skill venv import check failed — try re-running install.sh"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  MCP server : http://127.0.0.1:${MCP_PORT}/mcp  (tmux: $TMUX_SESSION)"
echo "  Sandbox URL: http://host.openshell.internal:${MCP_PORT}/mcp"
echo "  Server logs: tmux attach -t $TMUX_SESSION  (Ctrl-B D to detach)"
echo "  Log file   : tail -f $MCP_LOG_FILE"
echo ""
echo "  Next steps:"
echo "    1. Connect:  nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"Start a new ALFWorld game\""
echo "    3. Try: \"What task do I need to complete?\""
echo "    4. Try: \"Show me the current game frame\""
echo "    5. Try: \"What actions can I take right now?\""
echo "    6. Try: \"Take the next action to progress toward the goal\""
echo ""
echo "  If the agent doesn't find the skill, disconnect and reconnect."
echo -e "  ${YELLOW}Note: on first run AI2-THOR downloads ~390 MB. The server may take${NC}"
echo -e "  ${YELLOW}      60-90s to become ready. Check: tmux attach -t $TMUX_SESSION${NC}"
echo ""
echo -e "  ${YELLOW}After reboot: Xvfb is gone — restart it before re-running:${NC}"
echo -e "  ${YELLOW}  Xvfb :1 -screen 0 1024x768x24 &${NC}"
echo -e "  ${YELLOW}  bash $SCRIPT_DIR/install.sh $SANDBOX_NAME${NC}"
echo ""
