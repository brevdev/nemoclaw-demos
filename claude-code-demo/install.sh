#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
SESSIONS_PATH="/sandbox/.openclaw-data/agents/main/sessions/sessions.json"
SKILLS_BASE="/sandbox/.openclaw/skills"
CLAUDE_DIR="$HOME/.nemoclaw/claude-code"
PROJECTS_DIR="/sandbox/claude-projects"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

ssh_sandbox() {
  local sandbox="$1"; shift
  ssh -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o GlobalKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      -o ConnectTimeout=10 \
      -o ProxyCommand="$OPENSHELL_BIN ssh-proxy --gateway-name nemoclaw --name $sandbox" \
      "sandbox@openshell-$sandbox" "$@" 2>/dev/null
}

usage_exit() {
  echo ""
  echo "  Usage: ./install.sh [sandbox-name]"
  echo ""
  echo "  Installs Claude Code inside an OpenShell sandbox for NemoClaw."
  echo "  Claude builds apps in /sandbox/claude-projects/ and OpenClaw"
  echo "  manages the coding agent as a worker."
  echo ""
  echo "  API keys stay on the host — OpenShell injects credentials"
  echo "  at the gateway via a host-side proxy."
  echo ""
  echo "  Examples:"
  echo "    ./install.sh              # auto-detect sandbox"
  echo "    ./install.sh timbot       # target specific sandbox"
  echo ""
  exit 0
}

SANDBOX_NAME=""
for arg in "$@"; do
  case "$arg" in
    --help|-h) usage_exit ;;
    *) SANDBOX_NAME="$arg" ;;
  esac
done

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  Claude Code Integration for NemoClaw                  ║${NC}"
echo -e "${CYAN}  ║  Sandboxed Coding Agent — Keys Stay on Host            ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Detect openshell path ─────────────────────────────────────────
OPENSHELL_BIN=""
for candidate in \
  "$(command -v openshell 2>/dev/null || true)" \
  "$HOME/.local/bin/openshell" \
  "/usr/local/bin/openshell" \
  "/usr/bin/openshell"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    OPENSHELL_BIN="$candidate"
    break
  fi
done
[ -z "$OPENSHELL_BIN" ] && fail "openshell CLI not found. Is NemoClaw installed?"

# ─────────────────────────────────────────────────────────────────
# Step 1: Detect sandbox
# ─────────────────────────────────────────────────────────────────
if [ -z "$SANDBOX_NAME" ]; then
  SANDBOX_NAME=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox',''))
except: pass
" 2>/dev/null || true)
  if [ -z "${SANDBOX_NAME:-}" ]; then
    echo -n "  Sandbox name: "
    read -r SANDBOX_NAME
  fi
fi

[ -z "${SANDBOX_NAME:-}" ] && fail "No sandbox name. Usage: ./install.sh <sandbox-name>"
info "Target sandbox: $SANDBOX_NAME"

# ─────────────────────────────────────────────────────────────────
# Step 2: Prerequisites
# ─────────────────────────────────────────────────────────────────
echo ""
info "Checking prerequisites..."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found."
command -v nemoclaw >/dev/null 2>&1  || fail "nemoclaw CLI not found."
command -v python3 >/dev/null 2>&1   || fail "python3 not found."
command -v node >/dev/null 2>&1      || fail "node not found (needed to bundle Claude Code)."
command -v npm >/dev/null 2>&1       || fail "npm not found (needed to install Claude Code)."
"$OPENSHELL_BIN" sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME" || \
  fail "Sandbox '$SANDBOX_NAME' not found. Run 'nemoclaw onboard' first."
ok "Prerequisites OK"

# ─────────────────────────────────────────────────────────────────
# Step 2b: Verify SSH connectivity
# ─────────────────────────────────────────────────────────────────
info "Testing SSH connection to sandbox..."
SSH_TEST=$(ssh_sandbox "$SANDBOX_NAME" "echo OK" || echo "FAIL")
if [ "$SSH_TEST" != "OK" ]; then
  fail "Cannot SSH into sandbox '$SANDBOX_NAME'. Is it running?"
fi
ok "SSH connection verified"

# ─────────────────────────────────────────────────────────────────
# Step 2c: Detect node path inside sandbox
# ─────────────────────────────────────────────────────────────────
info "Detecting Node.js in sandbox..."
SANDBOX_NODE=$(ssh_sandbox "$SANDBOX_NAME" "command -v node" || true)
if [ -z "$SANDBOX_NODE" ]; then
  SANDBOX_NODE=$(ssh_sandbox "$SANDBOX_NAME" "ls /usr/local/bin/node 2>/dev/null || ls /usr/bin/node 2>/dev/null" || true)
fi
[ -z "$SANDBOX_NODE" ] && fail "Node.js not found in sandbox. Claude Code requires Node.js."
SANDBOX_NODE_VERSION=$(ssh_sandbox "$SANDBOX_NAME" "$SANDBOX_NODE --version" || echo "unknown")
ok "Node.js found: $SANDBOX_NODE ($SANDBOX_NODE_VERSION)"

# ─────────────────────────────────────────────────────────────────
# Step 3: Anthropic authentication
# ─────────────────────────────────────────────────────────────────
echo ""

CLAUDE_SSO_CREDS="$HOME/.claude/.credentials.json"
CONFIG_FILE="$HOME/.nemoclaw/claude-code-config.json"
AUTH_MODE=""

# Check what's already available
HAS_ANTHROPIC_KEY=false
HAS_SSO_TOKEN=false
if [ -f "$CREDS_PATH" ]; then
  HAS_KEY=$(python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
print('yes' if d.get('ANTHROPIC_API_KEY') else 'no')
" 2>/dev/null || echo "no")
  [ "$HAS_KEY" = "yes" ] && HAS_ANTHROPIC_KEY=true
fi
[ -f "$CLAUDE_SSO_CREDS" ] && HAS_SSO_TOKEN=true

# Check saved config
SAVED_AUTH_MODE=""
if [ -f "$CONFIG_FILE" ]; then
  SAVED_AUTH_MODE=$(python3 -c "
import json
d = json.load(open('$CONFIG_FILE'))
print(d.get('auth_mode', ''))
" 2>/dev/null || true)
fi

if [ -n "$SAVED_AUTH_MODE" ]; then
  if [ "$SAVED_AUTH_MODE" = "sso" ] && [ "$HAS_SSO_TOKEN" = true ]; then
    ok "Using SSO authentication (configured previously)"
    AUTH_MODE="sso"
  elif [ "$SAVED_AUTH_MODE" = "apikey" ] && [ "$HAS_ANTHROPIC_KEY" = true ]; then
    ok "Using API key authentication (configured previously)"
    AUTH_MODE="apikey"
  fi
fi

if [ -z "$AUTH_MODE" ]; then
  echo "  How do you want to authenticate with Anthropic?"
  echo ""
  echo "    1) Claude Code SSO — recommended"
  echo "       Works with any IdP Claude Code supports (NVIDIA, Google Workspace,"
  echo "       claude.ai subscription, etc.). Refresh token stays on the host;"
  echo "       a daemon rotates short-lived access tokens into the sandbox."
  echo ""
  echo "    2) Anthropic API key — for users without Claude Code SSO access"
  echo "       Key stays in ~/.nemoclaw/credentials.json on the host. A local"
  echo "       proxy (claude-proxy.py) injects it on outbound requests, so the"
  echo "       sk-ant-... key itself never enters the sandbox."
  echo ""
  echo -n "  Choice (1/2) [1]: "
  read -r AUTH_CHOICE

  case "${AUTH_CHOICE:-1}" in
    2) AUTH_MODE="apikey" ;;
    *) AUTH_MODE="sso" ;;
  esac
fi

if [ "$AUTH_MODE" = "sso" ]; then
  info "Setting up NVIDIA SSO authentication..."

  if [ "$HAS_SSO_TOKEN" = true ]; then
    ok "SSO token already exists at $CLAUDE_SSO_CREDS"
    echo -n "  Re-authenticate? (y/N): "
    read -r REAUTH
    if [[ "${REAUTH:-}" =~ ^[Yy] ]]; then
      HAS_SSO_TOKEN=false
    fi
  fi

  if [ "$HAS_SSO_TOKEN" = false ]; then
    echo ""
    echo -e "  ${YELLOW}A browser window will open for NVIDIA SSO login.${NC}"
    echo "  Complete the sign-in flow, then return here."
    echo ""

    CLAUDE_HOST_BIN="${CLAUDE_DIR}/node_modules/.bin/claude"
    if [ ! -x "$CLAUDE_HOST_BIN" ]; then
      # Need to install Claude Code on host first for login
      info "Installing Claude Code on host for SSO login..."
      mkdir -p "$CLAUDE_DIR"
      (cd "$CLAUDE_DIR" && npm init -y --silent >/dev/null 2>&1 && \
       npm install @anthropic-ai/claude-code --save --silent 2>&1) || \
        fail "npm install failed. Check network connectivity."
      CLAUDE_HOST_BIN="${CLAUDE_DIR}/node_modules/.bin/claude"
    fi

    echo -n "  Press Enter to open SSO login..."
    read -r

    "$CLAUDE_HOST_BIN" auth login 2>&1 || true

    if [ -f "$CLAUDE_SSO_CREDS" ]; then
      ok "SSO authentication successful — token stored on HOST at $CLAUDE_SSO_CREDS"
    else
      warn "SSO token file not found at $CLAUDE_SSO_CREDS"
      echo "  Claude Code may store credentials differently on your system."
      echo "  Checking alternative locations..."
      FOUND_CREDS=$(find "$HOME/.claude" -name "*.json" -type f 2>/dev/null | head -5)
      if [ -n "$FOUND_CREDS" ]; then
        echo "  Found:"
        echo "$FOUND_CREDS" | while read -r f; do echo "    $f"; done
      fi
      echo ""
      echo -n "  Continue anyway? (y/N): "
      read -r CONTINUE_SSO
      [[ "${CONTINUE_SSO:-}" =~ ^[Yy] ]] || fail "SSO setup incomplete."
    fi
  fi

  echo ""
  echo -e "  ${GREEN}SSO will be completed inside the sandbox after Claude Code is uploaded.${NC}"
  echo "  The token is short-lived and scoped to Claude API calls only."
  echo "  OpenShell network policy restricts what endpoints the sandbox can reach."

elif [ "$AUTH_MODE" = "apikey" ]; then
  if [ "$HAS_ANTHROPIC_KEY" = true ]; then
    ok "Anthropic API key found in $CREDS_PATH"
    echo -n "  Update API key? (y/N): "
    read -r UPDATE_KEY
    if [[ "${UPDATE_KEY:-}" =~ ^[Yy] ]]; then
      echo -n "  Anthropic API Key (sk-ant-...): "
      read -r NEW_KEY
      python3 -c "
import json
try: d = json.load(open('$CREDS_PATH'))
except: d = {}
d['ANTHROPIC_API_KEY'] = '''$NEW_KEY'''
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
"
      ok "API key updated"
    fi
  else
    info "No Anthropic API key found."
    echo ""
    echo -e "  ${YELLOW}Get your API key from: https://console.anthropic.com/settings/keys${NC}"
    echo ""
    echo -n "  Anthropic API Key (sk-ant-...): "
    read -r ANTHROPIC_KEY
    [ -z "$ANTHROPIC_KEY" ] && fail "API key is required."
    python3 -c "
import json
try: d = json.load(open('$CREDS_PATH'))
except: d = {}
d['ANTHROPIC_API_KEY'] = '''$ANTHROPIC_KEY'''
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
"
    ok "API key saved to $CREDS_PATH"
  fi
fi

# ─────────────────────────────────────────────────────────────────
# Step 3a: Command approval mode
# ─────────────────────────────────────────────────────────────────
echo ""

APPROVAL_MODE=""
SAVED_APPROVAL=""
if [ -f "$CONFIG_FILE" ]; then
  SAVED_APPROVAL=$(python3 -c "
import json
d = json.load(open('$CONFIG_FILE'))
print(d.get('approval_mode', ''))
" 2>/dev/null || true)
fi

if [ -n "$SAVED_APPROVAL" ]; then
  ok "Command approval: $SAVED_APPROVAL (configured previously)"
  echo -n "  Change? (y/N): "
  read -r CHANGE_APPROVAL
  if [[ ! "${CHANGE_APPROVAL:-}" =~ ^[Yy] ]]; then
    APPROVAL_MODE="$SAVED_APPROVAL"
  fi
fi

if [ -z "$APPROVAL_MODE" ]; then
  echo "  How should Claude Code handle command execution?"
  echo ""
  echo "    1) Auto-approve (recommended)"
  echo "       Claude Code runs commands without asking. Safe because the"
  echo "       OpenShell sandbox prevents damage beyond its boundaries."
  echo ""
  echo "    2) Ask user via Telegram/TUI"
  echo "       OpenClaw relays approval requests to you and waits for"
  echo "       your response before Claude Code proceeds. Slower but"
  echo "       gives you control over every command."
  echo ""
  echo -n "  Choice (1/2) [1]: "
  read -r APPROVAL_CHOICE

  case "${APPROVAL_CHOICE:-1}" in
    2) APPROVAL_MODE="ask_user" ;;
    *) APPROVAL_MODE="auto_approve" ;;
  esac
fi

info "Approval mode: $APPROVAL_MODE"

# ─────────────────────────────────────────────────────────────────
# Step 3a: Rotation policy (SSO only)
# ─────────────────────────────────────────────────────────────────
# Anthropic issues access tokens with an ~8h lifetime.  By default we
# refresh ~10 min before that expiry.  Users with a tighter threat model
# can choose to force shorter rotations — the daemon will re-push a new
# token after the cap, even though the current one is still valid.
REFRESH_LEAD=600
MAX_TOKEN_LIFETIME=0
if [ "$AUTH_MODE" = "sso" ]; then
  # Reuse previous choice if present
  SAVED_MAX_LIFETIME=""
  if [ -f "$CONFIG_FILE" ]; then
    SAVED_MAX_LIFETIME=$(python3 -c "
import json
try:
    d = json.load(open('$CONFIG_FILE'))
    print(d.get('max_token_lifetime_seconds', ''))
except: pass
" 2>/dev/null || true)
  fi

  if [ -n "$SAVED_MAX_LIFETIME" ]; then
    MAX_TOKEN_LIFETIME="$SAVED_MAX_LIFETIME"
    case "$MAX_TOKEN_LIFETIME" in
      0) ok "Rotation: near-expiry only (~8h windows, using previous choice)" ;;
      *) ok "Rotation: every ${MAX_TOKEN_LIFETIME}s (using previous choice)" ;;
    esac
  else
    echo ""
    echo "  How aggressively should the host daemon rotate the sandbox's access token?"
    echo "  (Anthropic issues tokens with ~8h expiry; rotating more often shrinks"
    echo "   the compromise window if the sandbox is ever breached.)"
    echo ""
    echo "    1) Every 2 hours — recommended"
    echo "       Balances security and overhead. Compromise window ≤ 2h,"
    echo "       ~4 extra refresh calls per day. Won't rotate mid-task."
    echo ""
    echo "    2) Hourly — tighter"
    echo "       Compromise window ≤ 1h. Still lightweight."
    echo ""
    echo "    3) Near server expiry only (~8h)"
    echo "       OAuth2 baseline. Minimal API calls but largest window."
    echo ""
    echo "    4) Custom: enter a number of seconds (min 1800)"
    echo ""
    echo -n "  Choice (1/2/3/4) [1]: "
    read -r ROT_CHOICE

    case "${ROT_CHOICE:-1}" in
      2) MAX_TOKEN_LIFETIME=3600 ;;
      3) MAX_TOKEN_LIFETIME=0 ;;
      4)
        echo -n "  Max token lifetime in seconds (>= 1800): "
        read -r CUSTOM_LIFETIME
        if [[ "$CUSTOM_LIFETIME" =~ ^[0-9]+$ ]] && [ "$CUSTOM_LIFETIME" -ge 1800 ]; then
          MAX_TOKEN_LIFETIME="$CUSTOM_LIFETIME"
        else
          warn "Invalid value; defaulting to 2h rotation"
          MAX_TOKEN_LIFETIME=7200
        fi
        ;;
      *) MAX_TOKEN_LIFETIME=7200 ;;
    esac
  fi
fi

# ─────────────────────────────────────────────────────────────────
# Step 3b: Save config
# ─────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$CONFIG_FILE")"
python3 -c "
import json
cfg = {
    'auth_mode': '$AUTH_MODE',
    'approval_mode': '$APPROVAL_MODE',
    'refresh_lead_seconds': $REFRESH_LEAD,
    'max_token_lifetime_seconds': $MAX_TOKEN_LIFETIME,
}
json.dump(cfg, open('$CONFIG_FILE', 'w'), indent=2)
"
ok "Config saved to $CONFIG_FILE"

# ─────────────────────────────────────────────────────────────────
# Step 3c: Host IP (used by all host-side proxies)
# ─────────────────────────────────────────────────────────────────
# The sandbox reaches the host through this IP. Proxies bind to
# 127.0.0.1 on the host; OpenShell forwards the sandbox's outbound
# connection to that loopback. Override with CLAUDE_PROXY_HOST if
# your networking is unusual.
HOST_IP="${CLAUDE_PROXY_HOST:-}"
[ -z "$HOST_IP" ] && HOST_IP=$( (hostname -I 2>/dev/null || true) | awk '{print $1}')
[ -z "$HOST_IP" ] && HOST_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
[ -z "$HOST_IP" ] && fail "Could not detect host IP. Set CLAUDE_PROXY_HOST=<ip> and retry."
info "Host IP (as seen from sandbox): $HOST_IP"

CLAUDE_PROXY_PORT="${CLAUDE_PROXY_PORT:-9202}"
GH_PROXY_PORT="${GITHUB_PROXY_PORT:-9203}"

# ─────────────────────────────────────────────────────────────────
# Step 3d: GitHub integration (optional)
# ─────────────────────────────────────────────────────────────────
echo ""
HAS_GITHUB_PAT=false
GITHUB_USER=""
if [ -f "$CREDS_PATH" ]; then
  HAS_PAT=$(python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
print('yes' if d.get('GITHUB_PAT') else 'no')
" 2>/dev/null || echo "no")
  [ "$HAS_PAT" = "yes" ] && HAS_GITHUB_PAT=true
  GITHUB_USER=$(python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
print(d.get('GITHUB_USER', ''))
" 2>/dev/null || true)
fi

if [ "$HAS_GITHUB_PAT" = true ] && [ -n "$GITHUB_USER" ]; then
  ok "GitHub: $GITHUB_USER (PAT in $CREDS_PATH)"
  echo -n "  Update? (y/N): "
  read -r UPDATE_GH
  if [[ "${UPDATE_GH:-}" =~ ^[Yy] ]]; then
    HAS_GITHUB_PAT=false
    GITHUB_USER=""
  fi
elif [ "$HAS_GITHUB_PAT" = true ]; then
  ok "GitHub PAT found — but username missing."
  echo -n "  GitHub username (e.g. tklawa-nvidia): "
  read -r GITHUB_USER
  if [ -n "$GITHUB_USER" ]; then
    python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
d['GITHUB_USER'] = '$GITHUB_USER'
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
"
    ok "GitHub username saved: $GITHUB_USER"
  fi
fi

if [ "$HAS_GITHUB_PAT" = false ]; then
  echo "  Optional: GitHub Personal Access Token for pushing code from sandbox."
  echo ""
  echo -e "  ${YELLOW}Create a fine-grained PAT at: https://github.com/settings/tokens?type=beta${NC}"
  echo "  Required permissions:"
  echo "    • Repository access: All repositories"
  echo "    • Administration:    Read and write  (create repos)"
  echo "    • Contents:          Read and write  (git push/pull)"
  echo "    • Metadata:          Read-only       (auto-selected)"
  echo ""
  echo "  (Press Enter to skip — you can add it later)"
  echo ""
  echo -n "  GitHub username (e.g. tklawa-nvidia): "
  read -r GITHUB_USER
  if [ -n "$GITHUB_USER" ]; then
    echo -n "  GitHub PAT (github_pat_... or ghp_...): "
    read -r GITHUB_PAT_INPUT
    if [ -n "$GITHUB_PAT_INPUT" ]; then
      python3 -c "
import json
try: d = json.load(open('$CREDS_PATH'))
except: d = {}
d['GITHUB_PAT'] = '''$GITHUB_PAT_INPUT'''
d['GITHUB_USER'] = '''$GITHUB_USER'''
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
"
      ok "GitHub credentials saved ($GITHUB_USER → $CREDS_PATH)"
      HAS_GITHUB_PAT=true

      # Validate the PAT by checking the authenticated user
      info "Validating PAT..."
      VALIDATED_USER=$(curl -s -H "Authorization: token $GITHUB_PAT_INPUT" \
        https://api.github.com/user 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('login',''))" 2>/dev/null || true)

      if [ -n "$VALIDATED_USER" ]; then
        if [ "$VALIDATED_USER" != "$GITHUB_USER" ]; then
          warn "PAT belongs to '$VALIDATED_USER', not '$GITHUB_USER'. Updating."
          GITHUB_USER="$VALIDATED_USER"
          python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
d['GITHUB_USER'] = '$VALIDATED_USER'
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
"
        fi
        ok "PAT validated: $VALIDATED_USER"
      else
        warn "Could not validate PAT (network issue?) — continuing anyway"
      fi
    else
      warn "No PAT provided. Skipping GitHub integration."
      GITHUB_USER=""
    fi
  else
    warn "Skipped — Claude Code can still build locally, just can't push to GitHub"
  fi
fi

# ─────────────────────────────────────────────────────────────────
# Step 4: Install Claude Code on the host
# ─────────────────────────────────────────────────────────────────
echo ""
info "Preparing Claude Code CLI..."

if [ -d "$CLAUDE_DIR/node_modules/@anthropic-ai/claude-code" ]; then
  ok "Claude Code already installed at $CLAUDE_DIR"
  echo -n "  Reinstall/update? (y/N): "
  read -r REINSTALL
  if [[ "${REINSTALL:-}" =~ ^[Yy] ]]; then
    rm -rf "$CLAUDE_DIR"
  fi
fi

if [ ! -d "$CLAUDE_DIR/node_modules/@anthropic-ai/claude-code" ]; then
  mkdir -p "$CLAUDE_DIR"
  info "Installing @anthropic-ai/claude-code via npm (this may take 1-2 minutes)..."
  (cd "$CLAUDE_DIR" && npm init -y --silent >/dev/null 2>&1 && \
   npm install @anthropic-ai/claude-code --save --silent 2>&1) || \
    fail "npm install failed. Check network connectivity."
  ok "Claude Code installed at $CLAUDE_DIR"
fi

CLAUDE_BIN="$CLAUDE_DIR/node_modules/.bin/claude"
[ -x "$CLAUDE_BIN" ] || fail "Claude Code binary not found at $CLAUDE_BIN"
CLAUDE_VERSION=$("$CLAUDE_BIN" --version 2>/dev/null || echo "unknown")
ok "Claude Code CLI: $CLAUDE_BIN (v$CLAUDE_VERSION)"

# ─────────────────────────────────────────────────────────────────
# Step 5: Bundle and upload Claude Code to sandbox
# ─────────────────────────────────────────────────────────────────
echo ""
info "Uploading Claude Code to sandbox..."

UPLOAD_DIR=$(mktemp -d /tmp/claude-code-upload-XXXXXX)
trap 'rm -rf "$UPLOAD_DIR"' EXIT

cp -r "$CLAUDE_DIR/node_modules" "$UPLOAD_DIR/node_modules"

# Create the wrapper. Anthropic auth is handled two ways depending on mode:
#   SSO    — claude-push-daemon.py writes a short-lived access token to
#            /sandbox/.openclaw-data/claude-code/oauth_token (picked up by
#            claude-runner.sh and exported as CLAUDE_CODE_OAUTH_TOKEN).
#   apikey — proxy.env contains `export ANTHROPIC_BASE_URL=…` pointing at
#            the host-side claude-proxy.py, which injects the real key.
# In both cases the long-lived secret stays on the host.
cat > "$UPLOAD_DIR/claude" << 'WRAPEOF'
#!/bin/bash
export DISABLE_AUTOUPDATER=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

if [ -f /sandbox/.config/claude-code/proxy.env ]; then
  source /sandbox/.config/claude-code/proxy.env
  if [ -n "${GITHUB_PROXY_URL:-}" ]; then
    git config --global http.https://github.com/.proxy "$GITHUB_PROXY_URL" 2>/dev/null || true
  fi
fi

# SSO path: short-lived OAuth token pushed in from the host daemon
CLAUDE_TOKEN_FILE="/sandbox/.openclaw-data/claude-code/oauth_token"
if [ -s "$CLAUDE_TOKEN_FILE" ]; then
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '\n\r' < "$CLAUDE_TOKEN_FILE")"
  export CLAUDE_CODE_OAUTH_TOKEN
fi

exec /sandbox/.config/claude-code/node_modules/.bin/claude "$@"
WRAPEOF
chmod +x "$UPLOAD_DIR/claude"

# Copy the standalone runner script (supports --background, --status, --result).
cp "$SCRIPT_DIR/claude-runner.sh" "$UPLOAD_DIR/claude-runner.sh"
chmod +x "$UPLOAD_DIR/claude-runner.sh"

"$OPENSHELL_BIN" sandbox upload "$SANDBOX_NAME" "$UPLOAD_DIR" /sandbox/.config/claude-code 2>/dev/null || \
  fail "Failed to upload Claude Code to sandbox."
ok "Claude Code uploaded to /sandbox/.config/claude-code/"

# Add to PATH via .bashrc
ssh_sandbox "$SANDBOX_NAME" \
  'grep -q "claude-code" /sandbox/.bashrc 2>/dev/null || echo "export PATH=\"/sandbox/.config/claude-code:\$PATH\"" >> /sandbox/.bashrc'
ok "claude + claude-runner.sh added to sandbox PATH"

# Create projects directory
ssh_sandbox "$SANDBOX_NAME" "mkdir -p $PROJECTS_DIR"
ok "Projects directory: $PROJECTS_DIR"

# ─────────────────────────────────────────────────────────────────
# Step 6: Authenticate Claude Code inside sandbox
# ─────────────────────────────────────────────────────────────────
echo ""

if [ "$AUTH_MODE" = "sso" ]; then
  info "Setting up NVIDIA SSO authentication..."

  CLAUDE_SSO_CREDS="$HOME/.claude/.credentials.json"

  # Check if host already has SSO credentials
  if [ -f "$CLAUDE_SSO_CREDS" ]; then
    HAS_TOKEN=$(python3 -c "
import json
d = json.load(open('$CLAUDE_SSO_CREDS'))
t = d.get('claudeAiOauth', {}).get('accessToken', '')
print('yes' if t else 'no')
" 2>/dev/null || echo "no")
  else
    HAS_TOKEN="no"
  fi

  if [ "$HAS_TOKEN" = "no" ]; then
    echo ""
    echo -e "  ${YELLOW}You need to complete NVIDIA SSO login on this host first.${NC}"
    echo "  A browser window will open for authentication."
    echo ""

    CLAUDE_HOST_BIN="${CLAUDE_DIR}/node_modules/.bin/claude"
    if [ ! -x "$CLAUDE_HOST_BIN" ]; then
      info "Installing Claude Code on host for SSO login..."
      mkdir -p "$CLAUDE_DIR"
      (cd "$CLAUDE_DIR" && npm init -y --silent >/dev/null 2>&1 && \
       npm install @anthropic-ai/claude-code --save --silent 2>&1) || \
        fail "npm install failed."
      CLAUDE_HOST_BIN="${CLAUDE_DIR}/node_modules/.bin/claude"
    fi

    echo -n "  Press Enter to open SSO login..."
    read -r
    "$CLAUDE_HOST_BIN" auth login 2>&1 || true

    if [ ! -f "$CLAUDE_SSO_CREDS" ]; then
      fail "SSO login did not produce credentials at $CLAUDE_SSO_CREDS"
    fi
    ok "SSO login complete on host"
  else
    ok "SSO credentials found on host at $CLAUDE_SSO_CREDS"
  fi

  # Remove any old credentials the sandbox may have from a previous
  # install.  With the push-daemon model the refresh token never
  # enters the sandbox.
  ssh_sandbox "$SANDBOX_NAME" "rm -f /sandbox/.claude/.credentials.json 2>/dev/null; rmdir /sandbox/.claude 2>/dev/null || true"
  ssh_sandbox "$SANDBOX_NAME" "mkdir -p /sandbox/.openclaw-data/claude-code"

  # Start (or restart) the host-side push daemon.  It refreshes the
  # access token against platform.claude.com before expiry and pushes
  # only the short-lived token into the sandbox.
  info "Starting Claude Code push daemon..."
  EXISTING_CC_PID=$(pgrep -f "python3.*claude-push-daemon.py" 2>/dev/null || true)
  if [ -n "$EXISTING_CC_PID" ]; then
    info "Stopping existing push daemon (PID $EXISTING_CC_PID)..."
    kill "$EXISTING_CC_PID" 2>/dev/null || true
    sleep 1
  fi

  # Build daemon flags from the rotation policy chosen earlier
  DAEMON_FLAGS=(--openshell "$OPENSHELL_BIN"
                --refresh-lead-seconds "$REFRESH_LEAD"
                --max-token-lifetime "$MAX_TOKEN_LIFETIME")

  # Bootstrap push so the token is present when we verify
  python3 "$SCRIPT_DIR/claude-push-daemon.py" "$SANDBOX_NAME" \
    "${DAEMON_FLAGS[@]}" --once 2>&1 | sed 's/^/    /'

  nohup python3 "$SCRIPT_DIR/claude-push-daemon.py" "$SANDBOX_NAME" \
    "${DAEMON_FLAGS[@]}" > /tmp/claude-push-daemon.log 2>&1 &
  CC_DAEMON_PID=$!
  sleep 1
  if kill -0 "$CC_DAEMON_PID" 2>/dev/null; then
    echo "$CC_DAEMON_PID" > "$HOME/.nemoclaw/claude-push-daemon.pid"
    if [ "$MAX_TOKEN_LIFETIME" -gt 0 ]; then
      ok "Push daemon running (PID $CC_DAEMON_PID) — rotating every ${MAX_TOKEN_LIFETIME}s; refresh token stays on host"
    else
      ok "Push daemon running (PID $CC_DAEMON_PID) — rotating near expiry; refresh token stays on host"
    fi
  else
    warn "Push daemon failed to start. See /tmp/claude-push-daemon.log"
  fi

  # Record a pointer in the NemoClaw credentials file so users can see
  # at a glance where Claude Code's OAuth creds live.  We do NOT copy
  # the tokens themselves — the refresh token must stay in the file
  # Claude Code itself writes to.
  mkdir -p "$(dirname "$CREDS_PATH")"
  [ -f "$CREDS_PATH" ] || echo '{}' > "$CREDS_PATH"
  python3 -c "
import json, os
p = os.path.expanduser('$CREDS_PATH')
d = json.load(open(p))
d['CLAUDE_CODE_SSO'] = {
    'path': '$CLAUDE_SSO_CREDS',
    'managed_by': 'claude auth login',
    'rotation': 'push-daemon',
    'max_token_lifetime_seconds': $MAX_TOKEN_LIFETIME,
    'note': 'OAuth tokens are owned by Claude Code. Do not edit by hand; re-run `claude auth login` to refresh.',
}
json.dump(d, open(p, 'w'), indent=2)
os.chmod(p, 0o600)
"
  ok "Recorded SSO pointer in $CREDS_PATH"

  # Verify Claude Code can authenticate inside the sandbox using the
  # pushed access token (via CLAUDE_CODE_OAUTH_TOKEN env var).
  AUTH_TEST=$(ssh_sandbox "$SANDBOX_NAME" \
    "TOK=\$(cat /sandbox/.openclaw-data/claude-code/oauth_token 2>/dev/null); \
     DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
     CLAUDE_CODE_OAUTH_TOKEN=\$TOK \
     /sandbox/.config/claude-code/node_modules/.bin/claude --dangerously-skip-permissions -p 'respond with PONG' < /dev/null 2>&1 | tail -1" || true)

  if echo "$AUTH_TEST" | grep -qi "PONG"; then
    ok "Claude Code authentication verified inside sandbox (access-token-only)"
  else
    warn "Auth test returned: $AUTH_TEST"
    warn "Claude Code may still work — check with: claude -p 'say hello'"
  fi

elif [ "$AUTH_MODE" = "apikey" ]; then
  info "Configuring API key authentication (host-side proxy mode)..."

  # Sanity check — the key must exist in the host credentials file.
  HAS_KEY=$(python3 -c "
import json
try: d = json.load(open('$CREDS_PATH'))
except: d = {}
print('yes' if d.get('ANTHROPIC_API_KEY') else 'no')
" 2>/dev/null || echo "no")
  [ "$HAS_KEY" = "yes" ] || fail "ANTHROPIC_API_KEY not found in $CREDS_PATH"

  ok "API key stays in $CREDS_PATH on host (never enters sandbox)"

  # Start (or restart) the host-side claude-proxy.py. The sandbox will
  # send its requests here; the proxy injects the real x-api-key before
  # forwarding to api.anthropic.com.
  info "Starting Claude API proxy on host..."
  EXISTING_CP_PID=$(pgrep -f "python3.*claude-proxy.py" 2>/dev/null || true)
  if [ -n "$EXISTING_CP_PID" ]; then
    info "Stopping existing Claude proxy (PID $EXISTING_CP_PID)..."
    kill "$EXISTING_CP_PID" 2>/dev/null || true
    sleep 1
  fi

  nohup python3 "$SCRIPT_DIR/claude-proxy.py" \
    --port "$CLAUDE_PROXY_PORT" --mode apikey \
    > /tmp/claude-proxy.log 2>&1 &
  CP_PID=$!
  sleep 2
  if kill -0 "$CP_PID" 2>/dev/null; then
    echo "$CP_PID" > "$HOME/.nemoclaw/claude-proxy.pid"
    ok "Claude proxy running (PID $CP_PID, port $CLAUDE_PROXY_PORT) — key stays on host"
  else
    fail "Claude proxy failed to start. See /tmp/claude-proxy.log"
  fi

  # Remove any in-sandbox key from an older install. The key never enters
  # the sandbox under this mode — only the base URL pointer does.
  ssh_sandbox "$SANDBOX_NAME" "mkdir -p /sandbox/.config/claude-code"
  ssh_sandbox "$SANDBOX_NAME" "sed -i '/^export ANTHROPIC_API_KEY=/d; /^ANTHROPIC_API_KEY=/d' /sandbox/.config/claude-code/proxy.env 2>/dev/null || true"

  # Deploy the base-URL pointer. We still set ANTHROPIC_API_KEY to a
  # placeholder because the Claude CLI refuses to start without it; the
  # host proxy overwrites the header with the real key.
  CLAUDE_PROXY_URL="http://${HOST_IP}:${CLAUDE_PROXY_PORT}"
  ssh_sandbox "$SANDBOX_NAME" "cat > /sandbox/.config/claude-code/proxy.env.anthropic << ENVEOF
export ANTHROPIC_BASE_URL=${CLAUDE_PROXY_URL}
export ANTHROPIC_API_KEY=openshell-managed
ENVEOF"
  # Merge Anthropic pointer with any existing (GitHub) proxy.env
  ssh_sandbox "$SANDBOX_NAME" "touch /sandbox/.config/claude-code/proxy.env; \
    grep -v '^export ANTHROPIC_BASE_URL=' /sandbox/.config/claude-code/proxy.env | \
    grep -v '^export ANTHROPIC_API_KEY=' > /sandbox/.config/claude-code/proxy.env.rest 2>/dev/null || true; \
    cat /sandbox/.config/claude-code/proxy.env.anthropic /sandbox/.config/claude-code/proxy.env.rest > /sandbox/.config/claude-code/proxy.env; \
    rm -f /sandbox/.config/claude-code/proxy.env.anthropic /sandbox/.config/claude-code/proxy.env.rest; \
    chmod 600 /sandbox/.config/claude-code/proxy.env"
  ok "Sandbox pointed at $CLAUDE_PROXY_URL (key injected on host)"

  # Record a pointer in NemoClaw credentials for discoverability.
  python3 -c "
import json, os
p = os.path.expanduser('$CREDS_PATH')
d = json.load(open(p))
d['CLAUDE_CODE_APIKEY'] = {
    'managed_by': 'claude-proxy.py',
    'proxy': '$CLAUDE_PROXY_URL',
    'note': 'API key stays on host; sandbox uses ANTHROPIC_BASE_URL to reach the host proxy.',
}
json.dump(d, open(p, 'w'), indent=2)
os.chmod(p, 0o600)
"
  ok "Recorded API-key pointer in $CREDS_PATH"
fi

# Write approval mode config into sandbox
ssh_sandbox "$SANDBOX_NAME" "mkdir -p /sandbox/.config/claude-code"
ssh_sandbox "$SANDBOX_NAME" "cat > /sandbox/.config/claude-code/config.json << CFGEOF
{\"approval_mode\": \"${APPROVAL_MODE}\"}
CFGEOF"
ok "Approval mode deployed: $APPROVAL_MODE"

# Create proxy.env for GitHub proxy URL (added in Step 7 if PAT exists)
ssh_sandbox "$SANDBOX_NAME" "touch /sandbox/.config/claude-code/proxy.env"

# ─────────────────────────────────────────────────────────────────
# Step 7: GitHub proxy (optional)
# ─────────────────────────────────────────────────────────────────
echo ""
if [ "$HAS_GITHUB_PAT" = true ]; then
  info "Setting up GitHub push proxy..."

  GH_PROXY_PORT="${GITHUB_PROXY_PORT:-9203}"
  GH_TOKEN_FILE="$HOME/.nemoclaw/github-proxy-token"

  # Generate or reuse a shared auth token for the proxy
  if [ -f "$GH_TOKEN_FILE" ]; then
    GH_PROXY_TOKEN=$(cat "$GH_TOKEN_FILE")
    ok "Proxy auth token exists"
  else
    GH_PROXY_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "$GH_PROXY_TOKEN" > "$GH_TOKEN_FILE"
    chmod 600 "$GH_TOKEN_FILE"
    ok "Proxy auth token generated"
  fi

  EXISTING_GH_PID=$(pgrep -f "python3.*github-proxy.py" 2>/dev/null || true)
  if [ -n "$EXISTING_GH_PID" ]; then
    info "Stopping existing GitHub proxy (PID $EXISTING_GH_PID)..."
    kill "$EXISTING_GH_PID" 2>/dev/null || true
    sleep 1
  fi

  nohup python3 "$SCRIPT_DIR/github-proxy.py" --port "$GH_PROXY_PORT" \
    --token "$GH_PROXY_TOKEN" > /tmp/github-proxy.log 2>&1 &
  GH_PROXY_PID=$!
  sleep 2

  if kill -0 "$GH_PROXY_PID" 2>/dev/null; then
    ok "GitHub proxy started (PID $GH_PROXY_PID, port $GH_PROXY_PORT, auth enabled)"
    echo "$GH_PROXY_PID" > "$HOME/.nemoclaw/github-proxy.pid"

    GH_PROXY_URL="http://${HOST_IP}:${GH_PROXY_PORT}"

    # Write proxy config for the runner script (token included so
    # git extra-header and curl can authenticate to the proxy)
    ssh_sandbox "$SANDBOX_NAME" "cat > /sandbox/.config/claude-code/proxy.env << ENVEOF
GITHUB_PROXY_URL=${GH_PROXY_URL}
GITHUB_USER=${GITHUB_USER}
GITHUB_PROXY_TOKEN=${GH_PROXY_TOKEN}
ENVEOF"
    ssh_sandbox "$SANDBOX_NAME" "chmod 600 /sandbox/.config/claude-code/proxy.env"

    # Forward-proxy approach (like Planet): git URL rewrite routes
    # https://github.com/ through the OpenShell transparent proxy
    # to the host-side proxy, which injects the PAT.
    ssh_sandbox "$SANDBOX_NAME" "\
      git config --global --unset http.https://github.com/.proxy 2>/dev/null || true; \
      git config --global url.\"${GH_PROXY_URL}/\".insteadOf 'https://github.com/' 2>/dev/null; \
      git config --global http.sslCAInfo /etc/openshell-tls/ca-bundle.pem 2>/dev/null; \
      git config --global http.\"${GH_PROXY_URL}/\".extraHeader 'X-Proxy-Token: ${GH_PROXY_TOKEN}' 2>/dev/null"
    ok "Git configured: https://github.com/ → proxy (PAT stays on host, auth token scoped)"
    [ -n "$GITHUB_USER" ] && ok "GitHub user: $GITHUB_USER (available in sandbox as \$GITHUB_USER)"
  else
    warn "GitHub proxy failed to start. Check /tmp/github-proxy.log"
    warn "You can still code locally — just can't push to GitHub from sandbox"
  fi
else
  info "GitHub push: skipped (no PAT configured)"
  echo "  Add later: edit ~/.nemoclaw/credentials.json and re-run ./install.sh"
fi

# ─────────────────────────────────────────────────────────────────
# Step 8: Apply network policy
# ─────────────────────────────────────────────────────────────────
echo ""
info "Applying network policy..."

CURRENT_POLICY=$("$OPENSHELL_BIN" policy get "$SANDBOX_NAME" --full 2>/dev/null | sed '1,/^---$/d')
POLICY_FILE=$(mktemp /tmp/claude-policy-XXXX.yaml)

echo "${CURRENT_POLICY:-version: 1}" | python3 - << PYEOF > "$POLICY_FILE"
import sys, re

policy = sys.stdin.read()

# Remove old claude-related blocks to avoid duplicates
for block in ['claude_api', 'claude_github', 'claude_code']:
    policy = re.sub(
        rf'  {block}:\n    name: {block}\n(?:    .*\n)*?(?=  \S|\Z)',
        '',
        policy
    )

if 'network_policies:' not in policy:
    policy = policy.rstrip() + '\nnetwork_policies:\n'

auth_mode = '$AUTH_MODE'
host_ip = '$HOST_IP'
claude_proxy_port = ${CLAUDE_PROXY_PORT:-9202}
gh_proxy_port = ${GH_PROXY_PORT:-9203}
has_github = '$HAS_GITHUB_PAT' == 'true'
node_path = '$SANDBOX_NODE'

if auth_mode == 'apikey':
    # API-key mode: sandbox talks to the host-side claude-proxy.py, which
    # injects the sk-ant-... key. The key never enters the sandbox, and
    # api.anthropic.com is NOT in the allow list — the sandbox can only
    # reach Anthropic via the policed proxy route.
    claude_block = f"""  claude_code:
    name: claude_code
    endpoints:
    - host: '{host_ip}'
      port: {claude_proxy_port}
      protocol: rest
      tls: passthrough
      enforcement: enforce
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
    binaries:
    - path: {node_path}
    - path: /sandbox/.config/claude-code/node_modules/.bin/claude
"""
else:
    # SSO mode: Claude Code connects directly to Anthropic using the
    # short-lived access token pushed in by claude-push-daemon.py.
    # OpenShell terminates TLS so it can enforce L7 rules.
    claude_block = """  claude_code:
    name: claude_code
    endpoints:
    - host: api.anthropic.com
      port: 443
      protocol: rest
      tls: terminate
      enforcement: enforce
      rules:
      - allow:
          method: POST
          path: /v1/messages
      - allow:
          method: POST
          path: /v1/messages/batches
      - allow:
          method: GET
          path: /v1/messages/batches/**
      - allow:
          method: POST
          path: /v1/complete
      - allow:
          method: GET
          path: /v1/organizations/**
      - allow:
          method: POST
          path: /v1/oauth/**
      - allow:
          method: GET
          path: /v1/oauth/**
      - allow:
          method: GET
          path: /api/oauth/**
      - allow:
          method: POST
          path: /api/oauth/**
    - host: statsig.anthropic.com
      port: 443
      protocol: rest
      tls: terminate
      enforcement: enforce
      rules:
      - allow:
          method: POST
          path: /**
    - host: sentry.io
      port: 443
      protocol: rest
      tls: terminate
      enforcement: enforce
      rules:
      - allow:
          method: POST
          path: /**
    - host: platform.claude.com
      port: 443
      protocol: rest
      tls: terminate
      enforcement: enforce
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
    - host: claude.ai
      port: 443
      protocol: rest
      tls: terminate
      enforcement: enforce
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
    binaries:
    - path: """ + node_path + """
    - path: /sandbox/.config/claude-code/node_modules/.bin/claude
"""

if has_github and host_ip:
    claude_block += f"""  claude_github:
    name: claude_github
    endpoints:
    - host: '{host_ip}'
      port: {gh_proxy_port}
      protocol: rest
      tls: passthrough
      enforcement: enforce
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
      - allow:
          method: PUT
          path: /**
      - allow:
          method: PATCH
          path: /**
    binaries:
    - path: /usr/bin/git
    - path: {node_path}
    - path: /sandbox/.config/claude-code/node_modules/.bin/claude
"""

if 'claude_code:' not in policy:
    policy = policy.rstrip() + '\n' + claude_block

print(policy)
PYEOF

"$OPENSHELL_BIN" policy set "$SANDBOX_NAME" --policy "$POLICY_FILE" --wait 2>&1 || warn "policy set returned non-zero"
rm -f "$POLICY_FILE"
ok "Network policy applied (Claude Code direct + GitHub proxy)"

# ─────────────────────────────────────────────────────────────────
# Step 9: Deploy Claude Code skill
# ─────────────────────────────────────────────────────────────────
echo ""
info "Deploying Claude Code skill..."

ssh_sandbox "$SANDBOX_NAME" "mkdir -p $SKILLS_BASE/claude-code/scripts"

cat "$SCRIPT_DIR/skills/claude-code/SKILL.md" | \
  ssh_sandbox "$SANDBOX_NAME" "cat > $SKILLS_BASE/claude-code/SKILL.md"
ok "SKILL.md deployed"

# ─────────────────────────────────────────────────────────────────
# Step 10: Clear agent sessions
# ─────────────────────────────────────────────────────────────────
echo ""
info "Clearing agent sessions..."
ssh_sandbox "$SANDBOX_NAME" "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true"
ok "Sessions cleared"

# ─────────────────────────────────────────────────────────────────
# Step 11: Verify
# ─────────────────────────────────────────────────────────────────
echo ""
info "Verifying installation..."

CLAUDE_CHECK=$(ssh_sandbox "$SANDBOX_NAME" \
  "[ -x /sandbox/.config/claude-code/claude ] && echo ok" || true)
RUNNER_CHECK=$(ssh_sandbox "$SANDBOX_NAME" \
  "[ -x /sandbox/.config/claude-code/claude-runner.sh ] && echo ok" || true)
SKILL_CHECK=$(ssh_sandbox "$SANDBOX_NAME" \
  "[ -f $SKILLS_BASE/claude-code/SKILL.md ] && echo ok" || true)
PROJECT_CHECK=$(ssh_sandbox "$SANDBOX_NAME" \
  "[ -d $PROJECTS_DIR ] && echo ok" || true)

[ "$CLAUDE_CHECK" = "ok" ]  && ok "Claude Code CLI installed in sandbox" || warn "Claude CLI not found"
[ "$RUNNER_CHECK" = "ok" ]  && ok "claude-runner.sh installed" || warn "Runner script not found"
[ "$SKILL_CHECK" = "ok" ]   && ok "Claude Code skill deployed" || warn "Skill not found"
[ "$PROJECT_CHECK" = "ok" ] && ok "Projects directory ready" || warn "Projects dir missing"

# ─────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Claude Code Integration installed!                     ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
if [ "$AUTH_MODE" = "sso" ]; then
echo "  Auth: Claude Code SSO — refresh token stays on host."
echo "        Short-lived access tokens are rotated into the sandbox"
echo "        by claude-push-daemon.py (see ~/.nemoclaw/claude-push-daemon.pid)."
echo "  The OpenShell network policy restricts which Anthropic endpoints are reachable."
else
echo "  Auth: Anthropic API key — key stays on host in $CREDS_PATH."
echo "        Sandbox talks to claude-proxy.py (port $CLAUDE_PROXY_PORT), which"
echo "        injects the key on outbound requests (see ~/.nemoclaw/claude-proxy.pid)."
fi
echo "  Approval mode: $APPROVAL_MODE"
echo ""
echo "  Projects directory: /sandbox/claude-projects/"
if [ "$HAS_GITHUB_PAT" = true ]; then
echo "  GitHub proxy:       PID $(cat "$HOME/.nemoclaw/github-proxy.pid" 2>/dev/null || echo '?') on port ${GH_PROXY_PORT:-9203}"
fi
echo ""
echo "  Next steps:"
echo "    1. Connect: nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"Build me a Python CLI tool that converts CSV to JSON\""
echo "    3. Try: \"Create a Flask REST API with user authentication\""
echo "    4. Try: \"List my claude projects\""
echo "    5. Try: \"Continue working on the csv-tools project\""
if [ "$HAS_GITHUB_PAT" = true ]; then
echo "    6. Try: \"Push the csv-tools project to GitHub as a PR\""
fi
echo ""
echo "  If the agent doesn't recognize the skill, disconnect and reconnect."
echo "  For Telegram: send any new message to start a fresh session."
echo ""
if [ "$HAS_GITHUB_PAT" = true ]; then
echo -e "  ${YELLOW}To stop GitHub proxy: kill \$(cat ~/.nemoclaw/github-proxy.pid)${NC}"
fi
if [ "$AUTH_MODE" = "sso" ]; then
echo -e "  ${YELLOW}To stop push daemon:  kill \$(cat ~/.nemoclaw/claude-push-daemon.pid)${NC}"
else
echo -e "  ${YELLOW}To stop Claude proxy: kill \$(cat ~/.nemoclaw/claude-proxy.pid)${NC}"
fi
echo -e "  ${YELLOW}To re-deploy:    ./setup.sh $SANDBOX_NAME${NC}"
echo ""
