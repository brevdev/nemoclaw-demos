#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
SESSIONS_PATH="/sandbox/.openclaw-data/agents/main/sessions/sessions.json"
SKILLS_BASE="/sandbox/.openclaw/skills"
TOKEN_PORT=9201

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

ssh_sandbox() {
  ssh -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      -o ProxyCommand="openshell ssh-proxy --gateway-name nemoclaw --name $SANDBOX_NAME" \
      "sandbox@openshell-$SANDBOX_NAME" "$@"
}

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  Planet API Integration Installer for NemoClaw          ║${NC}"
echo -e "${CYAN}  ║  Tier 1 Security — Host-Side API Proxy                 ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 0: Detect sandbox name ──────────────────────────────────
if [ -n "${1:-}" ]; then
  SANDBOX_NAME="$1"
else
  SANDBOX_NAME=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox',''))
except: pass
" 2>/dev/null || true)
  if [ -z "$SANDBOX_NAME" ]; then
    echo -n "  Sandbox name: "
    read -r SANDBOX_NAME
  fi
fi

[ -z "$SANDBOX_NAME" ] && fail "No sandbox name provided. Usage: ./install.sh <sandbox-name>"
info "Target sandbox: $SANDBOX_NAME"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────────
info "Checking prerequisites..."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found. Is NemoClaw installed?"
command -v nemoclaw >/dev/null 2>&1 || fail "nemoclaw CLI not found. Is NemoClaw installed?"
command -v python3 >/dev/null 2>&1 || fail "python3 not found."
openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME" || fail "Sandbox '$SANDBOX_NAME' not found. Run 'nemoclaw onboard' first."
ok "Prerequisites OK"

# ── Step 2: Planet API Key ───────────────────────────────────────
echo ""

HAS_PLANET_KEY=false
if [ -f "$CREDS_PATH" ]; then
  HAS_KEY=$(python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
print('yes' if d.get('PLANET_API_KEY') else 'no')
" 2>/dev/null || echo "no")
  [ "$HAS_KEY" = "yes" ] && HAS_PLANET_KEY=true
fi

if [ "$HAS_PLANET_KEY" = true ]; then
  ok "Planet API key found in $CREDS_PATH"
  echo ""
  echo -n "  Update API key? (y/N): "
  read -r UPDATE_KEY
  if [[ "${UPDATE_KEY:-}" =~ ^[Yy] ]]; then
    echo -n "  Planet API Key: "
    read -r NEW_KEY
    python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
d['PLANET_API_KEY'] = '$NEW_KEY'
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
print()
"
    ok "API key updated"
  fi
else
  info "No Planet API key found."
  echo ""
  echo -e "  ${YELLOW}Get your API key from: https://www.planet.com/account/#/user-settings${NC}"
  echo ""
  echo -n "  Planet API Key: "
  read -r PLANET_KEY
  [ -z "$PLANET_KEY" ] && fail "API key is required."
  python3 -c "
import json
try: d = json.load(open('$CREDS_PATH'))
except: d = {}
d['PLANET_API_KEY'] = '$PLANET_KEY'
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
print()
"
  ok "API key saved to $CREDS_PATH"
fi

PLANET_API_KEY=$(python3 -c "import json; print(json.load(open('$CREDS_PATH')).get('PLANET_API_KEY',''))")
[ -z "$PLANET_API_KEY" ] && fail "Planet API key is empty."

# ── Step 3: Detect host IP ───────────────────────────────────────
echo ""
HOST_IP="${PLANET_PROXY_HOST:-}"
if [ -z "$HOST_IP" ]; then
  # Linux
  HOST_IP=$( (hostname -I 2>/dev/null || true) | awk '{print $1}')
fi
if [ -z "$HOST_IP" ]; then
  # macOS
  HOST_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
fi
[ -z "$HOST_IP" ] && fail "Could not detect host IP. Set PLANET_PROXY_HOST env var."
info "Host IP: $HOST_IP (proxy will listen on 0.0.0.0:$TOKEN_PORT)"

# ── Step 4: Start/restart planet proxy ───────────────────────────
echo ""
info "Starting Planet API proxy on host..."

EXISTING_PID=$(pgrep -f "python3.*planet-proxy.py" 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
  info "Stopping existing proxy (PID $EXISTING_PID)..."
  kill "$EXISTING_PID" 2>/dev/null || true
  sleep 1
fi

nohup python3 "$SCRIPT_DIR/planet-proxy.py" --port "$TOKEN_PORT" \
  > /tmp/planet-proxy.log 2>&1 &
PROXY_PID=$!
sleep 2

if kill -0 "$PROXY_PID" 2>/dev/null; then
  ok "Planet proxy started (PID $PROXY_PID, port $TOKEN_PORT)"
else
  fail "Planet proxy failed to start. Check /tmp/planet-proxy.log"
fi

HEALTH=$(curl -sf "http://127.0.0.1:${TOKEN_PORT}/health" 2>/dev/null || true)
if [ "$HEALTH" = "ok" ]; then
  ok "Proxy health check passed"
else
  warn "Proxy health check failed (may still be starting)"
fi

# ── Step 5: Apply network policy ─────────────────────────────────
echo ""
info "Applying network policy..."

CURRENT_POLICY=$(openshell policy get "$SANDBOX_NAME" --full 2>/dev/null | sed '1,/^---$/d')
POLICY_FILE=$(mktemp /tmp/planet-policy-XXXX.yaml)

NEEDS_PROXY_BLOCK=true
if echo "$CURRENT_POLICY" | grep -q "planet_proxy"; then
  NEEDS_PROXY_BLOCK=false
fi

HAS_OLD_PLANET_BLOCK=false
if echo "$CURRENT_POLICY" | grep -q "planet_data_api"; then
  HAS_OLD_PLANET_BLOCK=true
fi

if [ "$NEEDS_PROXY_BLOCK" = true ] || [ "$HAS_OLD_PLANET_BLOCK" = true ]; then
  echo "$CURRENT_POLICY" | python3 -c "
import sys, re

host_ip = '$HOST_IP'
token_port = $TOKEN_PORT
remove_old = '$HAS_OLD_PLANET_BLOCK' == 'true'

policy = sys.stdin.read()

if remove_old:
    policy = re.sub(
        r'  planet_data_api:\n    name: planet_data_api\n(?:    .*\n)*?(?=  \S|\Z)',
        '',
        policy
    )

proxy_block = '''  planet_proxy:
    name: planet_proxy
    endpoints:
    - host: '{host}'
      port: {port}
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
    - path: /usr/local/bin/node
'''.format(host=host_ip, port=token_port)

if 'planet_proxy:' not in policy:
    policy = policy.rstrip() + '\n' + proxy_block

print(policy)
" > "$POLICY_FILE"

  openshell policy set "$SANDBOX_NAME" --policy "$POLICY_FILE" --wait 2>&1
  ok "Policy applied (planet_proxy block with host $HOST_IP:$TOKEN_PORT)"
  rm -f "$POLICY_FILE"
else
  ok "Policy already contains planet_proxy block"
fi

# ── Step 6: Deploy skill to sandbox ──────────────────────────────
echo ""
info "Deploying Planet skill to sandbox..."

ssh_sandbox "mkdir -p $SKILLS_BASE/planet/scripts" 2>/dev/null

upload_file() {
  local src="$1" dest="$2"
  cat "$src" | ssh_sandbox "cat > $dest" 2>/dev/null
}

upload_file "$SCRIPT_DIR/skills/planet/SKILL.md"                  "$SKILLS_BASE/planet/SKILL.md"
upload_file "$SCRIPT_DIR/skills/planet/scripts/planet-api.js"     "$SKILLS_BASE/planet/scripts/planet-api.js"
ok "Skill files uploaded"

ssh_sandbox "chmod +x $SKILLS_BASE/planet/scripts/planet-api.js" 2>/dev/null
ok "Script marked executable"

# ── Step 7: Write proxy URL to sandbox .env ──────────────────────
info "Writing proxy URL to sandbox..."

PROXY_URL="http://${HOST_IP}:${TOKEN_PORT}"

ssh_sandbox "cat > $SKILLS_BASE/planet/.env << ENVEOF
PLANET_PROXY_URL=${PROXY_URL}
ENVEOF" 2>/dev/null

ssh_sandbox "chmod 600 $SKILLS_BASE/planet/.env" 2>/dev/null
ok "Proxy URL deployed (no API key in sandbox)"

# ── Step 8: Clear agent sessions ─────────────────────────────────
echo ""
info "Clearing agent sessions..."
ssh_sandbox "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true" 2>/dev/null
ok "Sessions cleared"

# ── Step 9: Verify ───────────────────────────────────────────────
echo ""
info "Verifying installation..."

SKILL_CHECK=$(ssh_sandbox "[ -f $SKILLS_BASE/planet/scripts/planet-api.js ] && echo ok" 2>/dev/null || true)
ENV_CHECK=$(ssh_sandbox "grep -q PLANET_PROXY_URL $SKILLS_BASE/planet/.env 2>/dev/null && echo ok" 2>/dev/null || true)
PROXY_CHECK=$(curl -sf "http://127.0.0.1:${TOKEN_PORT}/health" 2>/dev/null || true)

[ "$SKILL_CHECK" = "ok" ] && ok "Planet skill installed" || warn "Planet skill not found"
[ "$ENV_CHECK" = "ok" ] && ok "Proxy URL configured (key stays on host)" || warn "Proxy URL not found"
[ "$PROXY_CHECK" = "ok" ] && ok "Planet proxy running on host" || warn "Planet proxy not responding"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete! (Tier 1 Security)               ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Security: API key stays on host. The sandbox only has the proxy URL."
echo "  To rotate the key: edit ~/.nemoclaw/credentials.json (takes effect immediately)."
echo ""
echo "  Next steps:"
echo "    1. Connect: nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"What satellite imagery types does Planet offer?\""
echo "    3. Try: \"Search for clear imagery over San Francisco from last month\""
echo "    4. Try: \"How many scenes cover New York this year?\""
echo "    5. Try: \"Show me assets for item 20260301_180000_00_2489\""
echo ""
echo "  If the agent doesn't recognize the skill, disconnect and reconnect."
echo "  For Telegram: send any message — a fresh session auto-creates."
echo ""
echo -e "  ${YELLOW}Note: No Docker rebuild or sandbox recreation needed.${NC}"
echo -e "  ${YELLOW}API key changes in credentials.json take effect immediately.${NC}"
echo ""
