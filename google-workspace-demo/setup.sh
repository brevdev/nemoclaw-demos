#!/usr/bin/env bash
set -euo pipefail

# Re-deploy Google Workspace integration (restart push daemon, re-upload gog,
# re-apply policy). Use after a reboot or sandbox reset. Skips OAuth and gog
# build -- run install.sh for first-time setup.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$HOME/.nemoclaw/gog-push-daemon.pid"
LOG_FILE="$HOME/.nemoclaw/gog-push-daemon.log"
GOGCLI_DIR="$HOME/.nemoclaw/gogcli"
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

SANDBOX=${1:-}
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

echo ""
echo -e "${CYAN}  Google Workspace -- Re-deploy (gog CLI + Push Daemon)${NC}"
echo ""

# Verify prerequisites
[ -f "$HOME/.nemoclaw/credentials.json" ] || fail "No credentials.json found. Run ./install.sh first."
command -v openshell >/dev/null 2>&1 || fail "openshell not found."

# Find gog binary
GOG_BIN=""
[ -x "$GOGCLI_DIR/bin/gog" ] && GOG_BIN="$GOGCLI_DIR/bin/gog"
if [ -z "$GOG_BIN" ]; then
  command -v gog >/dev/null 2>&1 && GOG_BIN="$(command -v gog)"
fi
[ -z "$GOG_BIN" ] && fail "gog binary not found. Run ./install.sh first to build it."
info "Using gog: $GOG_BIN"

# ── Restart push daemon ──────────────────────────────────────────────

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    info "Stopping push daemon (pid $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

info "Starting push daemon..."
nohup python3 "$SCRIPT_DIR/gog-push-daemon.py" "$SANDBOX" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

RETRIES=15
while (( RETRIES-- > 0 )); do
  if grep -q "Token pushed to sandbox" "$LOG_FILE" 2>/dev/null; then
    ok "Push daemon running (pid $(cat "$PID_FILE"))"
    break
  fi
  sleep 1
done
if (( RETRIES < 0 )); then
  warn "Push daemon did not push token within 15s. Check $LOG_FILE"
fi

# ── Upload config + credentials ──────────────────────────────────────

CREDS_PATH="$HOME/.nemoclaw/credentials.json"
CONFIG_UPLOAD=$(mktemp -d /tmp/gogcli-config-XXXXXX)

cat > "$CONFIG_UPLOAD/config.json" << 'CFGEOF'
{
  "default_timezone": "UTC"
}
CFGEOF

python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
creds = {
    'installed': {
        'client_id': d['GOOGLE_CLIENT_ID'],
        'client_secret': d['GOOGLE_CLIENT_SECRET'],
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'redirect_uris': ['http://localhost']
    }
}
with open('$CONFIG_UPLOAD/credentials.json', 'w') as f:
    json.dump(creds, f, indent=2)
"

openshell sandbox upload "$SANDBOX" "$CONFIG_UPLOAD" /sandbox/.config/gogcli 2>/dev/null || \
  warn "Config upload warning (non-fatal)"
rm -rf "$CONFIG_UPLOAD"
ok "Config + credentials uploaded"

# ── Re-upload gog binary + wrapper ───────────────────────────────────

BIN_UPLOAD=$(mktemp -d /tmp/gogcli-bin-XXXXXX)
trap 'rm -rf "$BIN_UPLOAD"' EXIT

cp "$GOG_BIN" "$BIN_UPLOAD/gog-bin"
chmod +x "$BIN_UPLOAD/gog-bin"

cat > "$BIN_UPLOAD/gog" << 'WRAPEOF'
#!/bin/bash
_TOKEN="$(cat /sandbox/.openclaw-data/gogcli/access_token 2>/dev/null)" || {
    echo "gog: access token not found. Is the push daemon running on the host?" >&2
    exit 1
}
if [ -f /sandbox/.openclaw-data/gogcli/token_expiry ]; then
    _EXP=$(cat /sandbox/.openclaw-data/gogcli/token_expiry)
    _NOW=$(date +%s)
    if [ "$_NOW" -gt "$_EXP" ]; then
        echo "gog: token expired. The push daemon will refresh it shortly." >&2
        exit 1
    fi
fi
export XDG_CONFIG_HOME=/sandbox/.config
exec env GOG_ACCESS_TOKEN="$_TOKEN" GOG_JSON=1 \
    /sandbox/.config/gogcli/bin/gog-bin "$@"
WRAPEOF
chmod +x "$BIN_UPLOAD/gog"

openshell sandbox upload "$SANDBOX" "$BIN_UPLOAD" /sandbox/.config/gogcli/bin 2>/dev/null || \
  fail "Failed to upload gog binary."
ok "gog binary re-uploaded"

# Re-upload gog SKILL.md so OpenClaw discovers gog as a tool
SKILL_UPLOAD=$(mktemp -d /tmp/gogcli-skill-XXXXXX)
trap 'rm -rf "$BIN_UPLOAD" "$SKILL_UPLOAD"' EXIT
mkdir -p "$SKILL_UPLOAD/gog"
cp "$SCRIPT_DIR/skills/gog/SKILL.md" "$SKILL_UPLOAD/gog/SKILL.md"

openshell sandbox upload "$SANDBOX" "$SKILL_UPLOAD/gog" /sandbox/.openclaw/skills/gog 2>/dev/null || \
  warn "Skill upload warning (non-fatal)"
ok "gog SKILL.md deployed"

openshell sandbox exec -n "$SANDBOX" -- bash -c \
  'grep -q "gogcli/bin" /sandbox/.bashrc 2>/dev/null || echo "export PATH=\"/sandbox/.config/gogcli/bin:\$PATH\"" >> /sandbox/.bashrc' 2>/dev/null
ok "PATH verified"

# ── Clear sessions ───────────────────────────────────────────────────

info "Clearing sessions..."
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true" 2>/dev/null
ok "Sessions cleared"

echo ""
echo -e "${GREEN}  Re-deploy complete.${NC}"
echo "  Push daemon: pid $(cat "$PID_FILE" 2>/dev/null || echo '?')"
echo "  Log: $LOG_FILE"
echo ""
echo "  Connect: nemoclaw $SANDBOX connect"
echo ""
