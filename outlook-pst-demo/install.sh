#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
MCP_PORT=9003
MCP_PID_FILE="/tmp/pst-mcp.pid"
MCP_LOG_FILE="/tmp/pst-mcp.log"

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
echo -e "${CYAN}  ║  Outlook PST MCP Demo Installer for NemoClaw             ║${NC}"
echo -e "${CYAN}  ║  PST Mailbox via MCP + OpenClaw Skill                   ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Clean up stale environment ───────────────────────────
info "Cleaning up stale environment..."
if [ -f "$MCP_PID_FILE" ]; then
  OLD_PID=$(cat "$MCP_PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    ok "Killed existing MCP server (PID $OLD_PID)"
  fi
  rm -f "$MCP_PID_FILE"
fi
STALE=$(pgrep -f "extract_pst_mcp_server" 2>/dev/null || true)
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

# Aspose.Email's .NET runtime requires libssl.so.1.1 (OpenSSL 1.x).
# Ubuntu 22.04+ ships only OpenSSL 3.x, which causes the server to crash
# mid-session with "No usable version of libssl was found".
if ! ldconfig -p | grep -q "libssl.so.1.1"; then
  warn "libssl1.1 not found — installing (required by Aspose.Email)..."
  LIBSSL_DEB=/tmp/libssl1.1.deb
  curl -fsSL "http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_amd64.deb" \
    -o "$LIBSSL_DEB" \
    || fail "Could not download libssl1.1. Check internet connectivity."
  sudo dpkg -i "$LIBSSL_DEB" || fail "dpkg install of libssl1.1 failed. Try: sudo dpkg -i $LIBSSL_DEB"
  rm -f "$LIBSSL_DEB"
  ok "libssl1.1 installed"
else
  ok "libssl1.1 already present"
fi
ok "Prerequisites OK"
echo ""

# ── Step 2: Load .env and resolve inference config ───────────────
info "Loading configuration..."

# Load .env if present (values do NOT override existing env vars)
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

# PST file path — optional, server falls back to its built-in sample
PST_PATH="${PST_PATH:-}"

ok "INFERENCE_API_KEY   : found"
ok "INFERENCE_PROVIDER  : $INFERENCE_PROVIDER_NAME (type=$INFERENCE_PROVIDER_TYPE)"
ok "INFERENCE_BASE_URL  : $INFERENCE_BASE_URL"
ok "INFERENCE_MODEL     : $INFERENCE_MODEL"
if [ -n "${PST_PATH:-}" ]; then
  ok "PST_PATH            : $PST_PATH"
else
  warn "PST_PATH not set — server will use its built-in sample PST"
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

# ── Step 3b: Enforce correct provider + inference model ──────────
# Runs every time — after the gateway is guaranteed to be live.
# nemoclaw onboard may have created a different provider/model;
# this always overrides it with what .env specifies.
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

# ── Step 5: Install Python dependencies on the host ─────────────
info "Installing Python dependencies for MCP server (host)..."
cd "$SCRIPT_DIR"
uv venv --python 3.10 --quiet
uv pip install --quiet --upgrade \
  fastmcp \
  colorama \
  python-dotenv \
  "Aspose.Email-for-Python-via-NET"
ok "Dependencies installed in .venv"
echo ""

# ── Step 6: Start MCP server as background process ──────────────
info "Starting PST MCP server in background..."

# Build env vars for the server process
SERVER_ENV="MCP_EXTRACT_PST_PORT=$MCP_PORT"
if [ -n "${PST_PATH:-}" ]; then
  SERVER_ENV="$SERVER_ENV PST_PATH=$(printf '%q' "$PST_PATH")"
fi
if [ -n "${ASPOSE_EMAIL_LICENSE_PATH:-}" ]; then
  SERVER_ENV="$SERVER_ENV ASPOSE_EMAIL_LICENSE_PATH=$(printf '%q' "$ASPOSE_EMAIL_LICENSE_PATH")"
fi

(
  cd "$SCRIPT_DIR"
  source .venv/bin/activate
  eval "export $SERVER_ENV"
  while true; do
    python extract_pst_mcp_server.py --port "$MCP_PORT"
    echo "[pst-mcp] Server exited (code $?), restarting in 2s..." >> "$MCP_LOG_FILE"
    sleep 2
  done
) >> "$MCP_LOG_FILE" 2>&1 &

echo $! > "$MCP_PID_FILE"
ok "MCP server started (PID $(cat $MCP_PID_FILE))"

# Wait up to 10 s for the port to open
SERVER_UP=false
for i in $(seq 1 10); do
  sleep 1
  if curl -s --max-time 1 "http://127.0.0.1:${MCP_PORT}/mcp" >/dev/null 2>&1; then
    SERVER_UP=true
    break
  fi
done

if [ "$SERVER_UP" = true ]; then
  ok "MCP server is up on port $MCP_PORT"
else
  # Check if the process is still alive
  if kill -0 "$(cat $MCP_PID_FILE 2>/dev/null)" 2>/dev/null; then
    warn "MCP server started but not responding yet — check: tail -f $MCP_LOG_FILE"
  else
    fail "MCP server process exited immediately. Check: cat $MCP_LOG_FILE"
  fi
fi
echo ""

# ── Step 7: Apply sandbox network policy ────────────────────────
info "Applying sandbox network policy..."
openshell policy set "$SANDBOX_NAME" \
  --policy "$SCRIPT_DIR/policy/sandbox_policy.yaml" \
  --wait
ok "Policy applied"
echo ""

# ── Step 8: Upload pst-mail-skills skill ────────────────────────
info "Uploading pst-mail-skills to sandbox..."
openshell sandbox upload "$SANDBOX_NAME" \
  "$SCRIPT_DIR/pst-mail-skills" \
  /sandbox/.openclaw-data/workspace/skills/pst-mail-skills
ok "Skill uploaded to /sandbox/.openclaw-data/workspace/skills/pst-mail-skills/"
echo ""

# ── Step 8b: Bootstrap skill venv with required deps ────────────
info "Setting up skill Python venv (fastmcp + deps)..."
SKILL_VENV=/sandbox/.openclaw-data/workspace/skills/pst-mail-skills/venv
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  python3 -m venv "$SKILL_VENV" \
  || fail "Failed to create skill venv at $SKILL_VENV inside sandbox '$SANDBOX_NAME'."
openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/pip" install -q fastmcp \
  || fail "pip install failed inside the skill venv. Check sandbox connectivity."
VENV_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import fastmcp; print('ok')" 2>/dev/null || true)
[ "$VENV_CHECK" = "ok" ] \
  && ok "Skill venv ready ($SKILL_VENV)" \
  || fail "Skill venv verification failed — 'import fastmcp' returned no output. Re-run install.sh."
echo ""

# ── Step 8c: Notify user to reconnect so OpenClaw picks up new skill + model ─
ok "Skill and inference model are configured — reconnect to activate them"
echo ""

# ── Step 9: Verify ───────────────────────────────────────────────
info "Verifying installation..."

MCP_UP=$(curl -s --max-time 3 "http://127.0.0.1:${MCP_PORT}/mcp" 2>&1 | wc -c || true)
[ "${MCP_UP:-0}" -gt 0 ] \
  && ok "MCP server responding on http://127.0.0.1:${MCP_PORT}/mcp" \
  || warn "MCP server not responding — check: cat $MCP_LOG_FILE"

SKILL_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f /sandbox/.openclaw-data/workspace/skills/pst-mail-skills/SKILL.md && echo ok" \
  2>/dev/null || true)
[ "$SKILL_CHECK" = "ok" ] \
  && ok "Skill confirmed in sandbox" \
  || warn "Skill not yet visible in sandbox — try reconnecting"

FASTMCP_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "$SKILL_VENV/bin/python3" -c "import fastmcp; print('ok')" \
  2>/dev/null || true)
[ "$FASTMCP_CHECK" = "ok" ] \
  && ok "fastmcp reachable via skill venv" \
  || warn "Skill venv import check failed — try re-running install.sh"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  MCP server : http://127.0.0.1:${MCP_PORT}/mcp  (PID $(cat $MCP_PID_FILE 2>/dev/null || echo '?'))"
echo "  Sandbox URL: http://host.openshell.internal:${MCP_PORT}/mcp"
echo "  Server logs: tail -f $MCP_LOG_FILE"
echo ""
echo "  Next steps:"
echo "    1. Connect:  nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"What folders are in my PST mailbox?\""
echo "    3. Try: \"Show me the 10 most recent emails\""
echo "    4. Try: \"Find all emails from alice@example.com\""
echo "    5. Try: \"Search for emails about 'project kickoff'\""
echo "    6. Try: \"How many emails are in the mailbox?\""
echo ""
if [ -z "${PST_PATH:-}" ]; then
  echo -e "  ${YELLOW}Note: No PST_PATH was set — the server is using its built-in sample PST.${NC}"
  echo -e "  ${YELLOW}To use your own file, add PST_PATH=/path/to/file.pst to $SCRIPT_DIR/.env and re-run.${NC}"
  echo ""
fi
echo "  If the agent doesn't find the skill, disconnect and reconnect."
echo -e "  ${YELLOW}To restart: kill \$(cat $MCP_PID_FILE) && bash $SCRIPT_DIR/install.sh $SANDBOX_NAME${NC}"
echo ""
