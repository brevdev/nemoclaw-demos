#!/usr/bin/env bash
set -euo pipefail

# ── NemoClaw Wakeup Updater ─────────────────────────────────────
# Re-deploys the wakeup script and skill WITHOUT touching WAKEUP.md.
# Use this after pulling repo updates.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.nemoclaw/wakeup"
SKILL_DEST="/sandbox/.openclaw-data/skills/nemoclaw-wakeup/SKILL.md"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

[ ! -f "$INSTALL_DIR/config.env" ] && fail "NemoClaw Wakeup not installed. Run install.sh first."
source "$INSTALL_DIR/config.env"

OPENSHELL_BIN="${WAKEUP_OPENSHELL:-$(command -v openshell 2>/dev/null || true)}"
[ -z "$OPENSHELL_BIN" ] && fail "openshell not found"

ssh_sandbox() {
  ssh -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o GlobalKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      -o ConnectTimeout=10 \
      -o ProxyCommand="$OPENSHELL_BIN ssh-proxy --gateway-name nemoclaw --name $WAKEUP_SANDBOX" \
      "sandbox@openshell-$WAKEUP_SANDBOX" "$@" 2>/dev/null
}

echo ""
echo -e "${CYAN}  NemoClaw Wakeup — Updating...${NC}"
echo ""
info "Sandbox: $WAKEUP_SANDBOX"

# Re-deploy skill with current config values
SKILL_FILE="$SCRIPT_DIR/skill/SKILL.md"
if [ -f "$SKILL_FILE" ]; then
  INSTALLED_AT="$(date +%Y-%m-%dT%H:%M:%S)"
  ssh_sandbox "mkdir -p $(dirname $SKILL_DEST)" 2>/dev/null || true
  sed -e "s/__INTERVAL__/$WAKEUP_INTERVAL/g" \
      -e "s/__INSTALLED_AT__/$INSTALLED_AT/g" \
      "$SKILL_FILE" | ssh_sandbox "cat > $SKILL_DEST"
  ok "Skill updated (interval: every ${WAKEUP_INTERVAL}m)"
else
  fail "skill/SKILL.md not found"
fi

# Re-generate wakeup.sh from install.sh template (preserves config)
info "Regenerating wakeup script..."
"$SCRIPT_DIR/install.sh" "$WAKEUP_SANDBOX" --interval "$WAKEUP_INTERVAL" 2>/dev/null && true

ok "Update complete (WAKEUP.md was NOT modified)"
echo ""
