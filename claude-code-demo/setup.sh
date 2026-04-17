#!/usr/bin/env bash
set -euo pipefail

# Re-deploy Claude Code integration (restart proxies, re-upload wrapper,
# config, SKILL.md, and network policy). Use after a reboot or sandbox
# reset. Skips npm install — run install.sh for first-time setup.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
CLAUDE_DIR="$HOME/.nemoclaw/claude-code"
SKILLS_BASE="/sandbox/.openclaw/skills"
SESSIONS_PATH="/sandbox/.openclaw-data/agents/main/sessions/sessions.json"

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
echo -e "${CYAN}  Claude Code — Re-deploy (Proxies + Skill)${NC}"
echo ""

# ── Detect openshell ──────────────────────────────────────────────
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
[ -z "$OPENSHELL_BIN" ] && fail "openshell CLI not found."

# ── Detect sandbox ────────────────────────────────────────────────
SANDBOX="${1:-}"
if [ -z "$SANDBOX" ]; then
  SANDBOX=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox',''))
except: pass
" 2>/dev/null || true)
fi
[ -z "$SANDBOX" ] && fail "Usage: ./setup.sh <sandbox-name>"
info "Sandbox: $SANDBOX"

ssh_sandbox() {
  ssh -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o GlobalKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      -o ConnectTimeout=10 \
      -o ProxyCommand="$OPENSHELL_BIN ssh-proxy --gateway-name nemoclaw --name $SANDBOX" \
      "sandbox@openshell-$SANDBOX" "$@" 2>/dev/null
}

# ── Verify claude-code is installed on host ───────────────────────
[ -d "$CLAUDE_DIR/node_modules/@anthropic-ai/claude-code" ] || \
  fail "Claude Code not installed. Run ./install.sh first."
ok "Claude Code found at $CLAUDE_DIR"

# ── SSH check ─────────────────────────────────────────────────────
SSH_TEST=$(ssh_sandbox "echo OK" || echo "FAIL")
[ "$SSH_TEST" = "OK" ] || fail "Cannot SSH into sandbox."
ok "SSH OK"

# ── Detect node path ─────────────────────────────────────────────
SANDBOX_NODE=$(ssh_sandbox "command -v node" || true)
[ -z "$SANDBOX_NODE" ] && SANDBOX_NODE=$(ssh_sandbox "ls /usr/local/bin/node 2>/dev/null || ls /usr/bin/node 2>/dev/null" || true)
[ -z "$SANDBOX_NODE" ] && fail "Node.js not found in sandbox."

# ── Read saved config ─────────────────────────────────────────────
CONFIG_FILE="$HOME/.nemoclaw/claude-code-config.json"
AUTH_MODE="apikey"
APPROVAL_MODE="auto_approve"
REFRESH_LEAD=600
MAX_TOKEN_LIFETIME=0
if [ -f "$CONFIG_FILE" ]; then
  AUTH_MODE=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('auth_mode','apikey'))" 2>/dev/null || echo "apikey")
  APPROVAL_MODE=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('approval_mode','auto_approve'))" 2>/dev/null || echo "auto_approve")
  REFRESH_LEAD=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('refresh_lead_seconds',600))" 2>/dev/null || echo "600")
  MAX_TOKEN_LIFETIME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('max_token_lifetime_seconds',0))" 2>/dev/null || echo "0")
fi
info "Auth: $AUTH_MODE | Approval: $APPROVAL_MODE"

# ── Host IP (needed by both proxies) ──────────────────────────────
HOST_IP="${CLAUDE_PROXY_HOST:-}"
[ -z "$HOST_IP" ] && HOST_IP=$( (hostname -I 2>/dev/null || true) | awk '{print $1}')
[ -z "$HOST_IP" ] && HOST_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
[ -z "$HOST_IP" ] && fail "Could not detect host IP. Set CLAUDE_PROXY_HOST=<ip> and retry."

CLAUDE_PROXY_PORT="${CLAUDE_PROXY_PORT:-9202}"
GH_PROXY_PORT="${GITHUB_PROXY_PORT:-9203}"

# ── Auth check ────────────────────────────────────────────────────
echo ""
if [ "$AUTH_MODE" = "sso" ]; then
  HOST_CC_CREDS="$HOME/.claude/.credentials.json"
  if [ ! -f "$HOST_CC_CREDS" ]; then
    fail "No host credentials at $HOST_CC_CREDS — run: claude auth login"
  fi

  # Clear any lingering full credentials from an older install —
  # the refresh token must not live in the sandbox.
  ssh_sandbox "rm -f /sandbox/.claude/.credentials.json 2>/dev/null; rmdir /sandbox/.claude 2>/dev/null || true"
  ssh_sandbox "mkdir -p /sandbox/.openclaw-data/claude-code"

  # Stop the API-key proxy if it was running from a previous apikey install
  EXISTING_CP_PID=$(pgrep -f "python3.*claude-proxy.py" 2>/dev/null || true)
  if [ -n "$EXISTING_CP_PID" ]; then
    info "Stopping Claude API proxy from previous apikey install (PID $EXISTING_CP_PID)..."
    kill "$EXISTING_CP_PID" 2>/dev/null || true
    rm -f "$HOME/.nemoclaw/claude-proxy.pid" 2>/dev/null || true
  fi

  # Restart push daemon
  EXISTING_CC_PID=$(pgrep -f "python3.*claude-push-daemon.py" 2>/dev/null || true)
  if [ -n "$EXISTING_CC_PID" ]; then
    info "Stopping existing push daemon (PID $EXISTING_CC_PID)..."
    kill "$EXISTING_CC_PID" 2>/dev/null || true
    sleep 1
  fi

  DAEMON_FLAGS=(--openshell "$OPENSHELL_BIN"
                --refresh-lead-seconds "$REFRESH_LEAD"
                --max-token-lifetime "$MAX_TOKEN_LIFETIME")

  python3 "$SCRIPT_DIR/claude-push-daemon.py" "$SANDBOX" \
    "${DAEMON_FLAGS[@]}" --once 2>&1 | sed 's/^/    /'

  nohup python3 "$SCRIPT_DIR/claude-push-daemon.py" "$SANDBOX" \
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

elif [ "$AUTH_MODE" = "apikey" ]; then
  HAS_KEY=$(python3 -c "
import json
try: d = json.load(open('$CREDS_PATH'))
except: d = {}
print('yes' if d.get('ANTHROPIC_API_KEY') else 'no')
" 2>/dev/null || echo "no")
  [ "$HAS_KEY" = "yes" ] || fail "ANTHROPIC_API_KEY not in $CREDS_PATH. Run ./install.sh."

  ok "API key stays in $CREDS_PATH on host (never enters sandbox)"

  # Stop the SSO push daemon if it was running from a previous SSO install
  EXISTING_CC_PID=$(pgrep -f "python3.*claude-push-daemon.py" 2>/dev/null || true)
  if [ -n "$EXISTING_CC_PID" ]; then
    info "Stopping push daemon from previous SSO install (PID $EXISTING_CC_PID)..."
    kill "$EXISTING_CC_PID" 2>/dev/null || true
    rm -f "$HOME/.nemoclaw/claude-push-daemon.pid" 2>/dev/null || true
  fi

  # Restart the claude-proxy (API key injector)
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
fi

# Deploy approval mode config
ssh_sandbox "cat > /sandbox/.config/claude-code/config.json << CFGEOF
{\"approval_mode\": \"${APPROVAL_MODE}\"}
CFGEOF"
ok "Approval config updated"

# Accumulate env vars for the single proxy.env we'll push to the sandbox.
# Each entry uses `export` so `source proxy.env` propagates to `claude`.
PROXY_ENV_BLOCK=""
if [ "$AUTH_MODE" = "apikey" ]; then
  CLAUDE_PROXY_URL="http://${HOST_IP}:${CLAUDE_PROXY_PORT}"
  PROXY_ENV_BLOCK="export ANTHROPIC_BASE_URL=${CLAUDE_PROXY_URL}
export ANTHROPIC_API_KEY=openshell-managed
"
fi

# ── Restart GitHub proxy (if PAT exists) ──────────────────────────
HAS_PAT=$(python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
print('yes' if d.get('GITHUB_PAT') else 'no')
" 2>/dev/null || echo "no")

GITHUB_USER=$(python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
print(d.get('GITHUB_USER', ''))
" 2>/dev/null || true)

if [ "$HAS_PAT" = "yes" ]; then
  GH_TOKEN_FILE="$HOME/.nemoclaw/github-proxy-token"
  GH_PROXY_TOKEN=""
  if [ -f "$GH_TOKEN_FILE" ]; then
    GH_PROXY_TOKEN=$(cat "$GH_TOKEN_FILE")
  fi

  EXISTING_GH=$(pgrep -f "python3.*github-proxy.py" 2>/dev/null || true)
  [ -n "$EXISTING_GH" ] && { kill "$EXISTING_GH" 2>/dev/null || true; sleep 1; }

  TOKEN_ARGS=""
  [ -n "$GH_PROXY_TOKEN" ] && TOKEN_ARGS="--token $GH_PROXY_TOKEN"

  nohup python3 "$SCRIPT_DIR/github-proxy.py" --port "$GH_PROXY_PORT" \
    $TOKEN_ARGS > /tmp/github-proxy.log 2>&1 &
  echo $! > "$HOME/.nemoclaw/github-proxy.pid"
  sleep 2
  kill -0 "$(cat "$HOME/.nemoclaw/github-proxy.pid")" 2>/dev/null && \
    ok "GitHub proxy: port $GH_PROXY_PORT (auth $([ -n "$GH_PROXY_TOKEN" ] && echo enabled || echo disabled))" || \
    warn "GitHub proxy may have failed"

  GH_PROXY_URL="http://${HOST_IP}:${GH_PROXY_PORT}"
  PROXY_ENV_BLOCK="${PROXY_ENV_BLOCK}export GITHUB_PROXY_URL=${GH_PROXY_URL}
export GITHUB_USER=${GITHUB_USER}
export GITHUB_PROXY_TOKEN=${GH_PROXY_TOKEN}
"
  ssh_sandbox "\
    git config --global --unset http.https://github.com/.proxy 2>/dev/null || true; \
    git config --global url.\"${GH_PROXY_URL}/\".insteadOf 'https://github.com/' 2>/dev/null; \
    git config --global http.sslCAInfo /etc/openshell-tls/ca-bundle.pem 2>/dev/null; \
    git config --global http.\"${GH_PROXY_URL}/\".extraHeader 'X-Proxy-Token: ${GH_PROXY_TOKEN}' 2>/dev/null"
  ok "GitHub proxy: forward proxy on $GH_PROXY_PORT"
  [ -n "$GITHUB_USER" ] && ok "GitHub user: $GITHUB_USER"
fi

# Write the unified proxy.env (Anthropic pointer + GitHub vars as needed).
if [ -n "$PROXY_ENV_BLOCK" ]; then
  ssh_sandbox "mkdir -p /sandbox/.config/claude-code"
  printf '%s' "$PROXY_ENV_BLOCK" | ssh_sandbox "cat > /sandbox/.config/claude-code/proxy.env && chmod 600 /sandbox/.config/claude-code/proxy.env"
  ok "proxy.env deployed (Anthropic${HAS_PAT:+ + GitHub})"
else
  ssh_sandbox "rm -f /sandbox/.config/claude-code/proxy.env 2>/dev/null || true"
fi

# ── Re-upload wrapper + runner ────────────────────────────────────
echo ""
info "Re-uploading wrapper scripts..."

UPLOAD_DIR=$(mktemp -d /tmp/claude-code-setup-XXXXXX)
trap 'rm -rf "$UPLOAD_DIR"' EXIT

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

CLAUDE_TOKEN_FILE="/sandbox/.openclaw-data/claude-code/oauth_token"
if [ -s "$CLAUDE_TOKEN_FILE" ]; then
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '\n\r' < "$CLAUDE_TOKEN_FILE")"
  export CLAUDE_CODE_OAUTH_TOKEN
fi

exec /sandbox/.config/claude-code/node_modules/.bin/claude "$@"
WRAPEOF
chmod +x "$UPLOAD_DIR/claude"

cp "$SCRIPT_DIR/skills/claude-code/SKILL.md" "$UPLOAD_DIR/SKILL.md"

"$OPENSHELL_BIN" sandbox upload "$SANDBOX" "$UPLOAD_DIR/claude" /sandbox/.config/claude-code/claude 2>/dev/null || \
  warn "Wrapper upload warning"
ok "Wrapper script updated"

# Re-upload the runner script (standalone file in repo)
info "Re-uploading runner script..."
ssh_sandbox "mkdir -p /sandbox/.config/claude-code/status"
cat "$SCRIPT_DIR/claude-runner.sh" | ssh_sandbox "cat > /sandbox/.config/claude-code/claude-runner.sh && chmod +x /sandbox/.config/claude-code/claude-runner.sh"
ok "Runner script updated"

# ── Re-deploy skill ──────────────────────────────────────────────
ssh_sandbox "mkdir -p $SKILLS_BASE/claude-code"
cat "$SCRIPT_DIR/skills/claude-code/SKILL.md" | ssh_sandbox "cat > $SKILLS_BASE/claude-code/SKILL.md"
ok "SKILL.md re-deployed"

# ── Re-apply network policy ──────────────────────────────────────
echo ""
info "Updating network policy..."

CURRENT_POLICY=$("$OPENSHELL_BIN" policy get "$SANDBOX" --full 2>/dev/null | sed '1,/^---$/d')
POLICY_FILE=$(mktemp /tmp/claude-policy-XXXX.yaml)

echo "${CURRENT_POLICY:-version: 1}" | python3 -c "
import sys, re

policy = sys.stdin.read()

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
claude_proxy_port = $CLAUDE_PROXY_PORT
gh_proxy_port = $GH_PROXY_PORT
has_github = '$HAS_PAT' == 'yes'
node_path = '$SANDBOX_NODE'

if auth_mode == 'apikey':
    # API-key mode: route to the host-side claude-proxy.py instead of
    # api.anthropic.com directly. The key never enters the sandbox.
    claude_block = f'''  claude_code:
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
'''
else:
    claude_block = '''  claude_code:
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
    - path: ''' + node_path + '''
    - path: /sandbox/.config/claude-code/node_modules/.bin/claude
'''

if has_github and host_ip:
    claude_block += f'''  claude_github:
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
'''

if 'claude_code:' not in policy:
    policy = policy.rstrip() + '\n' + claude_block

print(policy)
" > "$POLICY_FILE"

"$OPENSHELL_BIN" policy set "$SANDBOX" --policy "$POLICY_FILE" --wait 2>&1 || warn "Policy set returned non-zero"
rm -f "$POLICY_FILE"
ok "Network policy updated (Claude Code direct + GitHub proxy)"

# ── Clear sessions ────────────────────────────────────────────────
ssh_sandbox "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true"
ok "Sessions cleared"

# ── Done ──────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  Re-deploy complete.${NC}"
echo ""
if [ "$HAS_PAT" = "yes" ]; then
  echo "  GitHub proxy:    PID $(cat "$HOME/.nemoclaw/github-proxy.pid" 2>/dev/null || echo '?') on port ${GH_PROXY_PORT:-9203}"
fi
if [ "$AUTH_MODE" = "sso" ]; then
  echo "  Push daemon:     PID $(cat "$HOME/.nemoclaw/claude-push-daemon.pid" 2>/dev/null || echo '?')"
elif [ "$AUTH_MODE" = "apikey" ]; then
  echo "  Claude proxy:    PID $(cat "$HOME/.nemoclaw/claude-proxy.pid" 2>/dev/null || echo '?') on port ${CLAUDE_PROXY_PORT}"
fi
echo ""
echo "  Connect: nemoclaw $SANDBOX connect"
echo "  Try: \"Build me a Python script that...\""
echo ""
