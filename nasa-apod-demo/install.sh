#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
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

ssh_sandbox() {
  ssh -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      -o ProxyCommand="openshell ssh-proxy --gateway-name nemoclaw --name $SANDBOX_NAME" \
      "sandbox@openshell-$SANDBOX_NAME" "$@"
}

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  NASA APOD Skill Installer for NemoClaw                ║${NC}"
echo -e "${CYAN}  ║  No API key required — uses free DEMO_KEY             ║${NC}"
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
openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME" || fail "Sandbox '$SANDBOX_NAME' not found. Run 'nemoclaw onboard' first."
ok "Prerequisites OK"

# ── Step 2: Apply network policy ─────────────────────────────────
echo ""
info "Applying network policy..."

CURRENT_POLICY=$(openshell policy get "$SANDBOX_NAME" --full 2>/dev/null | sed '1,/^---$/d')
POLICY_FILE=$(mktemp /tmp/nasa-policy-XXXX.yaml)

if echo "$CURRENT_POLICY" | grep -q "nasa_apod"; then
  ok "Policy already contains nasa_apod block"
else
  echo "$CURRENT_POLICY" | python3 -c "
import sys

policy = sys.stdin.read()

nasa_block = '''  nasa_apod:
    name: nasa_apod
    endpoints:
    - host: api.nasa.gov
      port: 443
      protocol: rest
      tls: passthrough
      enforcement: enforce
      rules:
      - allow:
          method: GET
          path: /planetary/apod
    binaries:
    - path: /usr/bin/curl
    - path: /usr/local/bin/node
'''

policy = policy.rstrip() + '\n' + nasa_block
print(policy)
" > "$POLICY_FILE"

  openshell policy set "$SANDBOX_NAME" --policy "$POLICY_FILE" --wait 2>&1
  ok "Policy applied (nasa_apod: api.nasa.gov GET /planetary/apod)"
  rm -f "$POLICY_FILE"
fi

# ── Step 3: Deploy skill to sandbox ──────────────────────────────
echo ""
info "Deploying NASA APOD skill to sandbox..."

ssh_sandbox "mkdir -p $SKILLS_BASE/nasa-apod" 2>/dev/null

cat "$SCRIPT_DIR/skills/nasa-apod/SKILL.md" | ssh_sandbox "cat > $SKILLS_BASE/nasa-apod/SKILL.md" 2>/dev/null
ok "SKILL.md uploaded"

# ── Step 4: Clear agent sessions ─────────────────────────────────
echo ""
info "Clearing agent sessions..."
ssh_sandbox "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true" 2>/dev/null
ok "Sessions cleared"

# ── Step 5: Verify ───────────────────────────────────────────────
echo ""
info "Verifying installation..."

SKILL_CHECK=$(ssh_sandbox "[ -f $SKILLS_BASE/nasa-apod/SKILL.md ] && echo ok" 2>/dev/null || true)
API_CHECK=$(curl -sf "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('title') else 'fail')" 2>/dev/null || true)

[ "$SKILL_CHECK" = "ok" ] && ok "NASA APOD skill installed" || warn "NASA APOD skill not found"
[ "$API_CHECK" = "ok" ] && ok "NASA APOD API reachable (DEMO_KEY works)" || warn "NASA APOD API check failed (may be rate-limited)"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                 ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  No API key needed — uses NASA's free DEMO_KEY."
echo "  No host-side proxy — the sandbox calls api.nasa.gov directly."
echo ""
echo "  Next steps:"
echo "    1. Connect: nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"What's today's astronomy picture of the day?\""
echo "    3. Try: \"Show me NASA's space photo from June 3rd 2025\""
echo "    4. Try: \"Find 5 random stunning space photos\""
echo "    5. Try: \"Compare today's photo with last week's\""
echo ""
echo "  If the agent doesn't recognize the skill, disconnect and reconnect."
echo ""
