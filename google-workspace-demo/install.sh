#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
SESSIONS_PATH="/sandbox/.openclaw-data/agents/main/sessions/sessions.json"
PID_FILE="$HOME/.nemoclaw/gog-push-daemon.pid"
LOG_FILE="$HOME/.nemoclaw/gog-push-daemon.log"
OLD_TOKEN_PID="$HOME/.nemoclaw/google-token-server.pid"
GOGCLI_DIR="$HOME/.nemoclaw/gogcli"
GO_INSTALL_VERSION="1.23.8"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail()  { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

usage_exit() {
  echo ""
  echo "  Usage: ./install.sh [sandbox-name]"
  echo ""
  echo "  Installs Google Workspace integration (Gmail, Calendar, Drive, Docs, Sheets, Contacts, Tasks) via gog CLI"
  echo "  with a host-side push daemon. No sandbox recreation needed."
  echo ""
  echo "  The refresh token stays on the host. Only short-lived access tokens"
  echo "  are pushed into the sandbox (Tier 1 security)."
  echo ""
  echo "  Examples:"
  echo "    ./install.sh              # auto-detect sandbox"
  echo "    ./install.sh timbot       # target specific sandbox"
  echo ""
  exit 0
}

SANDBOX_ARG=""
for arg in "$@"; do
  case "$arg" in
    --help|-h) usage_exit ;;
    *) SANDBOX_ARG="$arg" ;;
  esac
done

# ─────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  Google Workspace Integration for NemoClaw             ║${NC}"
echo -e "${CYAN}  ║  Gmail Calendar Drive Docs Sheets Contacts Tasks       ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────────
# Step 1: Detect sandbox
# ─────────────────────────────────────────────────────────────────────
if [ -n "$SANDBOX_ARG" ]; then
  SANDBOX_NAME="$SANDBOX_ARG"
else
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

# ─────────────────────────────────────────────────────────────────────
# Step 2: Prerequisites
# ─────────────────────────────────────────────────────────────────────
echo ""
info "Checking prerequisites..."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found."
command -v nemoclaw >/dev/null 2>&1  || fail "nemoclaw CLI not found."
command -v python3 >/dev/null 2>&1   || fail "python3 not found."
command -v curl >/dev/null 2>&1      || fail "curl not found."
command -v git >/dev/null 2>&1       || fail "git not found (needed to build gog CLI)."
openshell sandbox list 2>/dev/null | grep -q "$SANDBOX_NAME" || fail "Sandbox '$SANDBOX_NAME' not found. Run 'nemoclaw onboard' first."
ok "Prerequisites OK"

# ─────────────────────────────────────────────────────────────────────
# Step 3: Google OAuth2 credentials
# ─────────────────────────────────────────────────────────────────────
echo ""

HAS_GOOGLE_CREDS=false
if [ -f "$CREDS_PATH" ]; then
  HAS_REFRESH=$(python3 -c "
import json
d = json.load(open('$CREDS_PATH'))
print('yes' if d.get('GOOGLE_REFRESH_TOKEN') else 'no')
" 2>/dev/null || echo "no")
  [ "$HAS_REFRESH" = "yes" ] && HAS_GOOGLE_CREDS=true
fi

if [ "$HAS_GOOGLE_CREDS" = true ]; then
  ok "Google OAuth credentials found in $CREDS_PATH"
  echo -n "  Re-run OAuth or update credentials? (y/N): "
  read -r UPDATE_CREDS
  if [[ "${UPDATE_CREDS:-}" =~ ^[Yy] ]]; then
    HAS_GOOGLE_CREDS=false
  fi
fi

if [ "$HAS_GOOGLE_CREDS" = false ]; then
  echo ""
  echo "  How do you want to provide Google credentials?"
  echo ""
  echo "    1) Paste credentials directly (if you already have Client ID, Secret, Refresh Token)"
  echo "    2) Run OAuth2 browser flow (opens localhost:3000 for Google sign-in)"
  echo ""
  echo -n "  Choice (1/2): "
  read -r CRED_METHOD

  if [ "${CRED_METHOD:-}" = "1" ]; then
    echo ""
    echo -n "  Google OAuth Client ID: "
    read -r INPUT_CLIENT_ID
    echo -n "  Google OAuth Client Secret: "
    read -r INPUT_CLIENT_SECRET
    echo -n "  Google Refresh Token: "
    read -r INPUT_REFRESH_TOKEN

    [ -z "$INPUT_CLIENT_ID" ] || [ -z "$INPUT_CLIENT_SECRET" ] || [ -z "$INPUT_REFRESH_TOKEN" ] && \
      fail "All three values are required."

    python3 -c "
import json
try: d = json.load(open('$CREDS_PATH'))
except: d = {}
d['GOOGLE_CLIENT_ID'] = '''$INPUT_CLIENT_ID'''
d['GOOGLE_CLIENT_SECRET'] = '''$INPUT_CLIENT_SECRET'''
d['GOOGLE_REFRESH_TOKEN'] = '''$INPUT_REFRESH_TOKEN'''
json.dump(d, open('$CREDS_PATH', 'w'), indent=2)
"
    ok "Credentials saved to $CREDS_PATH"
  else
    echo ""
    echo -e "  ${YELLOW}Before continuing, make sure you have:${NC}"
    echo "    1. A Google Cloud project with Gmail, Calendar, Drive, Docs, Sheets, People, and Tasks APIs enabled"
    echo "    2. An OAuth2 Desktop App credential (client ID + client secret)"
    echo "    3. Your Gmail address added as a test user in the OAuth consent screen"
    echo ""
    echo -e "  ${YELLOW}Get these at: https://console.cloud.google.com${NC}"
    echo ""
    echo -n "  Ready to continue? (Y/n): "
    read -r READY
    [[ "${READY:-}" =~ ^[Nn] ]] && { echo "  Run this script again when ready."; exit 0; }
    echo ""
    command -v node >/dev/null 2>&1 || fail "Node.js is required for OAuth flow."
    node "$SCRIPT_DIR/gmail-oauth-setup.js"
  fi
fi

python3 -c "
import json, sys
d = json.load(open('$CREDS_PATH'))
for k in ['GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REFRESH_TOKEN']:
    if not d.get(k):
        print(f'Missing {k} in credentials.json', file=sys.stderr)
        sys.exit(1)
" || fail "OAuth credentials missing from $CREDS_PATH."
ok "OAuth2 credentials verified"

# ─────────────────────────────────────────────────────────────────────
# Step 4: Locate or build gog CLI
# ─────────────────────────────────────────────────────────────────────
echo ""
info "Locating gog CLI..."

GOG_BIN=""

if [ -x "$GOGCLI_DIR/bin/gog" ]; then
  GOG_BIN="$GOGCLI_DIR/bin/gog"
  ok "gog CLI already built: $GOG_BIN"
elif command -v gog >/dev/null 2>&1; then
  GOG_BIN="$(command -v gog)"
  ok "gog CLI found on PATH: $GOG_BIN"
fi

if [ -z "$GOG_BIN" ]; then
  info "gog CLI not found, building from source..."

  # Install Go if needed
  go_ok() {
    command -v go >/dev/null 2>&1 || return 1
    local ver
    ver="$(go version 2>/dev/null | sed -E 's/.*go([0-9]+\.[0-9]+).*/\1/')" || return 1
    local major="${ver%%.*}" minor="${ver#*.}"
    (( major > 1 || (major == 1 && minor >= 21) ))
  }

  if ! go_ok; then
    info "Installing Go $GO_INSTALL_VERSION..."
    local_arch="amd64"
    case "$(uname -m)" in
      aarch64|arm64) local_arch="arm64" ;;
    esac
    local_os="linux"
    case "$(uname -s)" in
      Darwin) local_os="darwin" ;;
    esac
    tarball="go${GO_INSTALL_VERSION}.${local_os}-${local_arch}.tar.gz"
    mkdir -p "$HOME/.local"
    rm -rf "$HOME/.local/go"
    curl -fsSL "https://go.dev/dl/${tarball}" | tar -C "$HOME/.local" -xz
    export PATH="$HOME/.local/go/bin:$PATH"
    go version >/dev/null 2>&1 || fail "Go installation failed."
    ok "Go $(go version | sed -E 's/.*go([^ ]+).*/\1/') installed"
  else
    ok "Go $(go version | sed -E 's/.*go([^ ]+).*/\1/') available"
  fi

  if [ ! -d "$GOGCLI_DIR" ]; then
    info "Cloning gogcli..."
    if ! GIT_TERMINAL_PROMPT=0 git clone https://github.com/steipete/gogcli.git "$GOGCLI_DIR" 2>&1; then
      rm -rf "$GOGCLI_DIR"
      fail "Failed to clone gogcli. Check network connectivity."
    fi
  else
    info "Updating gogcli repo..."
    git -C "$GOGCLI_DIR" pull --ff-only 2>/dev/null || true
  fi

  info "Building gog CLI (this takes 1-2 minutes)..."
  if ! make -C "$GOGCLI_DIR" >/dev/null 2>&1; then
    if ! command -v make >/dev/null 2>&1; then
      fail "gog CLI build failed: 'make' is not installed. Fix with: sudo apt install -y make build-essential"
    fi
    fail "gog CLI build failed. Run 'make -C $GOGCLI_DIR' manually to see the error."
  fi
  GOG_BIN="$GOGCLI_DIR/bin/gog"
  [ -x "$GOG_BIN" ] || fail "gog binary not found after build."
  ok "gog CLI built: $GOG_BIN"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 5: Stop old services, start push daemon
# ─────────────────────────────────────────────────────────────────────
echo ""

# Stop old HTTP token-server.py from the previous integration approach
if [ -f "$OLD_TOKEN_PID" ]; then
  OLD_PID=$(cat "$OLD_TOKEN_PID" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    info "Stopping old token server (pid $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$OLD_TOKEN_PID"
fi

# Stop existing push daemon if running
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    info "Stopping existing push daemon (pid $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

info "Starting push daemon..."
nohup python3 "$SCRIPT_DIR/gog-push-daemon.py" "$SANDBOX_NAME" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

RETRIES=15
while (( RETRIES-- > 0 )); do
  if grep -q "Token pushed to sandbox" "$LOG_FILE" 2>/dev/null; then
    ok "Push daemon running (pid $(cat "$PID_FILE")), initial token pushed"
    break
  fi
  sleep 1
done
if (( RETRIES < 0 )); then
  warn "Push daemon did not push token within 15s. Check $LOG_FILE"
fi

# ─────────────────────────────────────────────────────────────────────
# Step 6: Upload gog CLI to sandbox
# ─────────────────────────────────────────────────────────────────────
echo ""
info "Uploading gog CLI to sandbox..."

# Config directory: timezone + OAuth client credentials (client_id/secret only).
# For desktop OAuth apps, client_id and client_secret are NOT treated as secrets
# by Google. The real credential (refresh token) stays on the host. gog requires
# credentials.json to be present even when using GOG_ACCESS_TOKEN.
CONFIG_UPLOAD=$(mktemp -d /tmp/gogcli-config-XXXXXX)
trap 'rm -rf "$CONFIG_UPLOAD"' EXIT

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

openshell sandbox upload "$SANDBOX_NAME" "$CONFIG_UPLOAD" /sandbox/.config/gogcli 2>/dev/null || \
  warn "Config upload warning (non-fatal)"

# Upload gog-bin (actual binary) + gog (wrapper script)
BIN_UPLOAD=$(mktemp -d /tmp/gogcli-bin-XXXXXX)
trap 'rm -rf "$CONFIG_UPLOAD" "$BIN_UPLOAD"' EXIT

cp "$GOG_BIN" "$BIN_UPLOAD/gog-bin"
chmod +x "$BIN_UPLOAD/gog-bin"

# Wrapper reads the pushed access token from the writable data directory
# and passes it to gog-bin via GOG_ACCESS_TOKEN, bypassing gog's keyring.
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

openshell sandbox upload "$SANDBOX_NAME" "$BIN_UPLOAD" /sandbox/.config/gogcli/bin 2>/dev/null || \
  fail "Failed to upload gog binary to sandbox."
ok "gog binary + wrapper uploaded"

# Add to PATH via .bashrc
openshell sandbox exec -n "$SANDBOX_NAME" -- bash -c \
  'grep -q "gogcli/bin" /sandbox/.bashrc 2>/dev/null || echo "export PATH=\"/sandbox/.config/gogcli/bin:\$PATH\"" >> /sandbox/.bashrc' 2>/dev/null
ok "gog added to sandbox PATH"

# Upload gog SKILL.md so OpenClaw discovers gog as a tool
SKILL_UPLOAD=$(mktemp -d /tmp/gogcli-skill-XXXXXX)
trap 'rm -rf "$CONFIG_UPLOAD" "$BIN_UPLOAD" "$SKILL_UPLOAD"' EXIT
mkdir -p "$SKILL_UPLOAD/gog"
cp "$SCRIPT_DIR/skills/gog/SKILL.md" "$SKILL_UPLOAD/gog/SKILL.md"

openshell sandbox upload "$SANDBOX_NAME" "$SKILL_UPLOAD/gog" /sandbox/.openclaw/skills/gog 2>/dev/null || \
  warn "Skill upload warning (non-fatal)"
ok "gog SKILL.md deployed to /sandbox/.openclaw/skills/gog/"

# ─────────────────────────────────────────────────────────────────────
# Step 7: Clean up old integration artifacts
# ─────────────────────────────────────────────────────────────────────
echo ""
info "Cleaning up old custom skill files..."
openshell sandbox exec -n "$SANDBOX_NAME" -- bash -c \
  'rm -rf /sandbox/.openclaw/skills/gmail /sandbox/.openclaw/skills/gcalendar 2>/dev/null; true' 2>/dev/null
ok "Old custom skills removed (replaced by gog CLI)"

# ─────────────────────────────────────────────────────────────────────
# Step 8: Apply network + filesystem policy
# ─────────────────────────────────────────────────────────────────────
echo ""
info "Applying network policy..."

CURRENT_POLICY=$(openshell policy get --full "$SANDBOX_NAME" 2>/dev/null | awk '/^---/{found=1; next} found{print}')

POLICY_FILE=$(mktemp /tmp/gog-policy-XXXXXX.yaml)
echo "${CURRENT_POLICY:-version: 1}" > "$POLICY_FILE"

# Line-by-line policy merge: preserves existing entries exactly,
# removes old google blocks, adds new ones, inserts read_only entry.
python3 - "$POLICY_FILE" << 'PYEOF'
import sys

policy_file = sys.argv[1]
with open(policy_file) as f:
    lines = f.readlines()

SKIP_BLOCKS = {'google_apis', 'google_token_server', 'google_gmail', 'google_calendar', 'google_drive', 'google_docs', 'google_sheets', 'google_contacts', 'google_tasks'}
NEW_ENTRY = '  - /sandbox/.config/gogcli/bin\n'

out = []
skip_until_next_block = False
has_gogcli_readonly = False
inserted_readonly = False

for line in lines:
    stripped = line.rstrip('\n')

    if '/sandbox/.config/gogcli/bin' in stripped:
        has_gogcli_readonly = True

    # If currently skipping a block, consume its indented/blank lines
    if skip_until_next_block:
        if stripped == '' or stripped.startswith('    '):
            continue
        else:
            skip_until_next_block = False
            # Fall through: this line may start another block to skip

    # Check if this line starts a network policy block we want to remove
    block_match = False
    for b in SKIP_BLOCKS:
        if stripped == f'  {b}:':
            skip_until_next_block = True
            block_match = True
            break
    if block_match:
        continue

    # Insert read_only entry right before read_write section
    if not inserted_readonly and stripped == '  read_write:':
        if not has_gogcli_readonly:
            out.append(NEW_ENTRY)
        inserted_readonly = True

    out.append(line)

# Ensure network_policies: section exists
policy_text = ''.join(out)
if 'network_policies:' not in policy_text:
    out.append('network_policies:\n')

# Append new Google Workspace policy blocks (match openshell YAML format)
google = """\
  google_gmail:
    name: google_gmail
    endpoints:
    - host: gmail.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
      - allow:
          method: PATCH
          path: /**
      - allow:
          method: DELETE
          path: /**
    binaries:
    - path: /sandbox/.config/gogcli/bin/gog-bin
  google_calendar:
    name: google_calendar
    endpoints:
    - host: www.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
      - allow:
          method: PATCH
          path: /**
      - allow:
          method: DELETE
          path: /**
    - host: calendar.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
      - allow:
          method: PATCH
          path: /**
      - allow:
          method: DELETE
          path: /**
    binaries:
    - path: /sandbox/.config/gogcli/bin/gog-bin
  google_drive:
    name: google_drive
    endpoints:
    - host: drive.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
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
      - allow:
          method: DELETE
          path: /**
    binaries:
    - path: /sandbox/.config/gogcli/bin/gog-bin
  google_docs:
    name: google_docs
    endpoints:
    - host: docs.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
      - allow:
          method: PATCH
          path: /**
    binaries:
    - path: /sandbox/.config/gogcli/bin/gog-bin
  google_sheets:
    name: google_sheets
    endpoints:
    - host: sheets.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
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
    - path: /sandbox/.config/gogcli/bin/gog-bin
  google_contacts:
    name: google_contacts
    endpoints:
    - host: people.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
      rules:
      - allow:
          method: GET
          path: /**
    binaries:
    - path: /sandbox/.config/gogcli/bin/gog-bin
  google_tasks:
    name: google_tasks
    endpoints:
    - host: tasks.googleapis.com
      port: 443
      protocol: rest
      enforcement: enforce
      tls: terminate
      rules:
      - allow:
          method: GET
          path: /**
      - allow:
          method: POST
          path: /**
      - allow:
          method: PATCH
          path: /**
      - allow:
          method: DELETE
          path: /**
    binaries:
    - path: /sandbox/.config/gogcli/bin/gog-bin
"""

out.append(google)

with open(policy_file, "w") as f:
    f.writelines(out)
PYEOF

openshell policy set --policy "$POLICY_FILE" --wait "$SANDBOX_NAME" 2>&1 || warn "policy set returned non-zero"
rm -f "$POLICY_FILE"
ok "Policy applied (gmail + calendar + drive + docs + sheets + contacts + tasks)"

# ─────────────────────────────────────────────────────────────────────
# Step 9: Clear agent sessions
# ─────────────────────────────────────────────────────────────────────
echo ""
info "Clearing agent sessions..."
openshell sandbox exec -n "$SANDBOX_NAME" -- bash -c \
  "[ -f $SESSIONS_PATH ] && echo '{}' > $SESSIONS_PATH || true" 2>/dev/null
ok "Sessions cleared"

# ─────────────────────────────────────────────────────────────────────
# Step 10: Verify
# ─────────────────────────────────────────────────────────────────────
echo ""
info "Verifying installation..."
GOG_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- bash -c \
  '[ -x /sandbox/.config/gogcli/bin/gog ] && echo ok' 2>/dev/null || true)
TOKEN_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- bash -c \
  '[ -f /sandbox/.openclaw-data/gogcli/access_token ] && echo ok' 2>/dev/null || true)

[ "$GOG_CHECK" = "ok" ] && ok "gog CLI installed in sandbox" || warn "gog CLI not found in sandbox"
[ "$TOKEN_CHECK" = "ok" ] && ok "Access token present" || warn "Access token not yet available (daemon may still be starting)"

# ─────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                 ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Security: Tier 1 -- refresh token stays on host, short-lived access"
echo "  tokens pushed to sandbox via openshell. No network port exposed."
echo ""
echo "  Push daemon: pid $(cat "$PID_FILE" 2>/dev/null || echo '?')"
echo "  Log file:    $LOG_FILE"
echo ""
echo "  Services: Gmail, Calendar, Drive, Docs, Sheets, Contacts (read), Tasks"
echo ""
echo "  Next steps:"
echo "    1. Connect: nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"Check my email\""
echo "    3. Try: \"What's on my calendar today?\""
echo "    4. Try: \"Send an email to someone@example.com about the hackathon\""
echo "    5. Try: \"List my recent Google Drive files\""
echo "    6. Try: \"Read my meeting notes doc\""
echo "    7. Try: \"Read cell A1:D10 from my budget spreadsheet\""
echo "    8. Try: \"Create a task to follow up with the client\""
echo "    9. Try: \"Look up Sarah in my contacts\""
echo ""
echo "  If the agent doesn't recognize gog, disconnect and reconnect."
echo "  For Telegram: send any new message to start a fresh session."
echo ""
echo "  To stop the daemon:  kill \$(cat $PID_FILE)"
echo "  To re-deploy:        ./setup.sh $SANDBOX_NAME"
echo "  Full reinstall:      ./install.sh $SANDBOX_NAME"
echo ""
