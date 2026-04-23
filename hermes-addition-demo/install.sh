#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"

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
echo -e "${CYAN}  ║  Hermes Agent Demo Installer for NemoClaw Sandbox        ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Clean up stale environment ───────────────────────────
info "Cleaning up stale environment..."
STALE=$(pgrep -f "hermes-agent" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  kill $STALE 2>/dev/null || true
  ok "Killed stale hermes-agent process(es)"
fi
ok "Environment clean"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────────
info "Checking prerequisites..."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found. Is NemoClaw installed?"
command -v nemoclaw  >/dev/null 2>&1 || fail "nemoclaw CLI not found. Is NemoClaw installed?"
command -v python3   >/dev/null 2>&1 || fail "python3 not found."
command -v git       >/dev/null 2>&1 || fail "git not found."
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

ok "INFERENCE_API_KEY   : found"
ok "INFERENCE_PROVIDER  : $INFERENCE_PROVIDER_NAME (type=$INFERENCE_PROVIDER_TYPE)"
ok "INFERENCE_BASE_URL  : $INFERENCE_BASE_URL"
ok "INFERENCE_MODEL     : $INFERENCE_MODEL"
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

# ── Step 5: Apply sandbox network policy ────────────────────────
# Must happen BEFORE the hermes install so that curl/pip/uv inside the
# sandbox can reach astral.sh, pypi.org, nodejs.org, github.com, npm, etc.
info "Applying sandbox network policy..."
openshell policy set "$SANDBOX_NAME" \
  --policy "$SCRIPT_DIR/policy/sandbox_policy.yaml" \
  --wait
ok "Policy applied"
echo ""

# ── Step 6: Clone hermes-agent on HOST, upload to sandbox ────────
# We upload the repo so its scripts/install.sh is available inside the
# sandbox.  The hermes installer then clones fresh to ~/.hermes/hermes-agent
# using git (allowed by the network policy; SSL verify disabled below).
HERMES_REPO="https://github.com/NousResearch/hermes-agent.git"

cd "$SCRIPT_DIR"

if [ -d "hermes-agent/.git" ]; then
  info "hermes-agent already cloned — pulling latest..."
  git -C hermes-agent pull --ff-only \
    && ok "hermes-agent updated" \
    || warn "git pull failed — proceeding with existing clone."
else
  [ -d "hermes-agent" ] && rm -rf hermes-agent
  info "Cloning $HERMES_REPO on host..."
  git clone "$HERMES_REPO" hermes-agent \
    || fail "git clone failed. Check host network connectivity and try again."
  ok "Cloned to $SCRIPT_DIR/hermes-agent"
fi

info "Uploading hermes-agent from host to sandbox at /sandbox/hermes-agent ..."
openshell sandbox upload "$SANDBOX_NAME" hermes-agent /sandbox/hermes-agent
ok "hermes-agent uploaded to /sandbox/hermes-agent"
echo ""

# ── Step 6b: Pre-install uv inside sandbox (host download) ───────
# The hermes installer fetches uv via curl to astral.sh, which is blocked
# by the sandbox network proxy.  Work around this by downloading the uv
# binary on the HOST (unrestricted) and uploading it directly into the
# sandbox at ~/.local/bin/uv — the installer checks there first and skips
# the curl step entirely when the binary is already present.
info "Pre-installing uv into sandbox (downloading on host to bypass proxy)..."
SANDBOX_ARCH=$(openshell sandbox exec -n "$SANDBOX_NAME" -- uname -m 2>/dev/null || echo "x86_64")
case "$SANDBOX_ARCH" in
  x86_64)  UV_TRIPLE="x86_64-unknown-linux-gnu" ;;
  aarch64) UV_TRIPLE="aarch64-unknown-linux-gnu" ;;
  armv7l)  UV_TRIPLE="armv7-unknown-linux-gnueabihf" ;;
  *)       warn "Unknown sandbox arch '$SANDBOX_ARCH', defaulting to x86_64"
           UV_TRIPLE="x86_64-unknown-linux-gnu" ;;
esac
UV_TMP="$(mktemp -d)/uv-download"
mkdir -p "$UV_TMP"
UV_URL="https://github.com/astral-sh/uv/releases/latest/download/uv-${UV_TRIPLE}.tar.gz"
info "Fetching $UV_URL ..."
curl -fsSL "$UV_URL" | tar -xz -C "$UV_TMP" \
  || fail "Failed to download uv binary from GitHub. Check host network connectivity."
UV_BIN=$(find "$UV_TMP" -name "uv" -type f | head -1)
[ -z "$UV_BIN" ] && fail "uv binary not found in downloaded archive."
chmod +x "$UV_BIN"
# Create ~/.local/bin in the sandbox and upload the binary there
openshell sandbox exec -n "$SANDBOX_NAME" -- mkdir -p /sandbox/.local/bin
openshell sandbox upload "$SANDBOX_NAME" "$UV_BIN" /sandbox/.local/bin/uv
openshell sandbox exec -n "$SANDBOX_NAME" -- chmod +x /sandbox/.local/bin/uv
UV_VER=$(openshell sandbox exec -n "$SANDBOX_NAME" -- /sandbox/.local/bin/uv --version 2>/dev/null || true)
[ -n "$UV_VER" ] \
  && ok "uv pre-installed in sandbox: $UV_VER" \
  || fail "uv upload succeeded but binary is not executable in sandbox."
rm -rf "$UV_TMP"
echo ""

# ── Step 7: Install hermes (Python only — no npm / no playwright) ─
# We bypass the hermes installer script entirely and replicate only the
# Python-side steps: venv creation, pip install, config setup, and PATH.
# This skips the install_node_deps() function that pulls in playwright.
INSTALL_DIR=/sandbox/hermes-agent
HERMES_HOME=/sandbox/.hermes

info "Creating Python venv in sandbox..."
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c "cd $INSTALL_DIR && /sandbox/.local/bin/uv venv venv --python 3.11" \
  || fail "uv venv failed."
ok "venv created"

info "Installing hermes Python dependencies (uv pip install)..."
info "This may take a few minutes on first run."
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c "export VIRTUAL_ENV=$INSTALL_DIR/venv && cd $INSTALL_DIR && /sandbox/.local/bin/uv pip install -e '.[all]'" \
  || fail "uv pip install failed. Check sandbox pypi access."
ok "Python dependencies installed"

info "Setting up ~/.hermes config directory..."
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c "mkdir -p $HERMES_HOME/cron $HERMES_HOME/sessions $HERMES_HOME/logs $HERMES_HOME/pairing $HERMES_HOME/hooks $HERMES_HOME/image_cache $HERMES_HOME/audio_cache $HERMES_HOME/memories $HERMES_HOME/skills"
ok "Config directory ready at $HERMES_HOME"

# Point hermes at the sandbox's internal inference route (inference.local).
# This is the same endpoint OpenClaw uses — no external API key needed.
# The API key value "unused" is intentional; the sandbox proxy ignores it.
info "Configuring hermes to use sandbox inference route (inference.local)..."
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c "printf 'model:\n  provider: custom\n  base_url: \"https://inference.local/v1\"\n  default: \"${INFERENCE_MODEL}\"\n' > $HERMES_HOME/config.yaml"
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c "printf 'OPENAI_API_KEY=unused\nOPENAI_BASE_URL=https://inference.local/v1\n' > $HERMES_HOME/.env"
ok "hermes model: ${INFERENCE_MODEL} via inference.local"

info "Syncing bundled skills..."
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c "$INSTALL_DIR/venv/bin/python $INSTALL_DIR/tools/skills_sync.py 2>/dev/null || cp -r $INSTALL_DIR/skills/. $HERMES_HOME/skills/" \
  || warn "Skills sync failed — skills may not be available."
ok "Skills synced"

info "Linking hermes binary to /sandbox/.local/bin ..."
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c "ln -sf $INSTALL_DIR/venv/bin/hermes /sandbox/.local/bin/hermes"
ok "hermes binary linked at /sandbox/.local/bin/hermes"

info "Adding ~/.local/bin to PATH in sandbox .bashrc ..."
openshell sandbox exec -n "$SANDBOX_NAME" -- sh -c 'grep -q "\.local/bin" ~/.bashrc 2>/dev/null || echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> ~/.bashrc'
ok "PATH updated"
echo ""

# ── Step 8: Restart the OpenClaw gateway ────────────────────────
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

HERMES_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c 'PATH="$HOME/.local/bin:$PATH" command -v hermes 2>/dev/null || echo "not found"' \
  2>/dev/null || true)
if [ "$HERMES_CHECK" != "not found" ] && [ -n "$HERMES_CHECK" ]; then
  ok "hermes binary found at: $HERMES_CHECK"
else
  warn "hermes not found on PATH inside sandbox."
  warn "Add to ~/.bashrc inside sandbox:  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Next steps:"
echo "    1. Connect:  openshell sandbox connect $SANDBOX_NAME"
echo "    2. Run:      export PATH=\"\$HOME/.local/bin:\$PATH\""
echo "    3. Run:      hermes"
echo ""
echo "  If the agent doesn't find hermes, disconnect and reconnect."
echo ""
