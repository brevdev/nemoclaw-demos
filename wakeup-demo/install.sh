#!/usr/bin/env bash
set -euo pipefail

# ── NemoClaw Wakeup Installer ───────────────────────────────────
# Sets up a host-side cron job that periodically wakes the OpenClaw
# agent inside an OpenShell sandbox via SSH. The agent reads its
# instructions from /sandbox/.openclaw-data/workspace/WAKEUP.md.
#
# Trigger path: host cron → SSH → openclaw agent → reads WAKEUP.md
# SSH is used instead of `openshell sandbox exec` because exec is
# unreliable (hangs/aborts). SSH via openshell ssh-proxy is fast
# (~400ms) and always completes.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.nemoclaw/wakeup"
SANDBOXES_JSON="$HOME/.nemoclaw/sandboxes.json"
WAKEUP_MD_PATH="/sandbox/.openclaw-data/workspace/WAKEUP.md"
SKILL_DEST="/sandbox/.openclaw-data/skills/nemoclaw-wakeup/SKILL.md"

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
  echo "  Usage: ./install.sh [options] [sandbox-name]"
  echo ""
  echo "  Options:"
  echo "    --interval <minutes>  Wakeup interval in minutes (default: 10)"
  echo "    --uninstall           Remove wakeup cron job and files"
  echo "    --status              Show current wakeup status"
  echo "    -h, --help            Show this help"
  echo ""
  echo "  The agent reads its instructions from WAKEUP.md inside the sandbox."
  echo "  Edit it via the TUI, Telegram, or manually."
  echo ""
  exit 0
}

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

# ── Parse arguments ───────────────────────────────────────────────
SANDBOX_NAME=""
INTERVAL=""
DO_UNINSTALL=false
DO_STATUS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval)  INTERVAL="$2"; shift 2 ;;
    --uninstall) DO_UNINSTALL=true; shift ;;
    --status)    DO_STATUS=true; shift ;;
    -h|--help)   usage_exit ;;
    -*)          fail "Unknown option: $1" ;;
    *)
      if [ -z "$SANDBOX_NAME" ]; then
        SANDBOX_NAME="$1"; shift
      else
        fail "Unknown argument: $1"
      fi
      ;;
  esac
done

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

# ── Status mode ───────────────────────────────────────────────────
if [ "$DO_STATUS" = true ]; then
  echo ""
  echo -e "${CYAN}  NemoClaw Wakeup Status${NC}"
  echo ""

  if [ -f "$INSTALL_DIR/config.env" ]; then
    source "$INSTALL_DIR/config.env"
    ok "Installed"
    echo "    Sandbox:   ${WAKEUP_SANDBOX:-unknown}"
    echo "    Interval:  every ${WAKEUP_INTERVAL:-?} minutes"
    echo "    Trigger:   SSH (via openshell ssh-proxy)"
    echo "    Log:       $INSTALL_DIR/wakeup.log"
  else
    warn "Not installed"
  fi

  CRON_LINE=$(crontab -l 2>/dev/null | grep "nemoclaw-wakeup" || true)
  if [ -n "$CRON_LINE" ]; then
    ok "Cron job active"
    echo "    $CRON_LINE"
  else
    warn "No cron job found"
  fi

  if [ -f "$INSTALL_DIR/wakeup.log" ]; then
    echo ""
    echo "  Last 5 log entries:"
    tail -10 "$INSTALL_DIR/wakeup.log" | grep "^[0-9]" | tail -5 | while read -r line; do
      echo "    $line"
    done
  fi

  echo ""
  exit 0
fi

# ── Uninstall mode ────────────────────────────────────────────────
if [ "$DO_UNINSTALL" = true ]; then
  echo ""
  echo -e "${CYAN}  Removing NemoClaw Wakeup...${NC}"
  echo ""

  EXISTING=$(crontab -l 2>/dev/null | grep -v "nemoclaw-wakeup" || true)
  if [ -n "$EXISTING" ]; then
    echo "$EXISTING" | crontab -
  else
    crontab -r 2>/dev/null || true
  fi
  ok "Cron job removed"

  # Also remove old heartbeat cron entries
  EXISTING2=$(crontab -l 2>/dev/null | grep -v "nemoclaw-heartbeat" || true)
  if [ -n "$EXISTING2" ]; then
    echo "$EXISTING2" | crontab -
  fi

  rm -rf "$INSTALL_DIR"
  rm -rf "$HOME/.nemoclaw/heartbeat" 2>/dev/null || true
  ok "Wakeup files removed"

  echo ""
  echo -e "${GREEN}  NemoClaw Wakeup uninstalled.${NC}"
  echo ""
  exit 0
fi

# ── Main install ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  NemoClaw Wakeup Installer                             ║${NC}"
echo -e "${CYAN}  ║  Host-Side Cron → SSH → Wakes OpenClaw Agent           ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Detect sandbox ────────────────────────────────────────
if [ -z "$SANDBOX_NAME" ]; then
  SANDBOX_NAME=$(python3 -c "
import json
try:
    d = json.load(open('$SANDBOXES_JSON'))
    print(d.get('defaultSandbox',''))
except: pass
" 2>/dev/null || true)

  if [ -z "$SANDBOX_NAME" ]; then
    SANDBOX_LIST=$("$OPENSHELL_BIN" sandbox list 2>/dev/null | tail -n +2 | awk '{print $1}' | head -5)
    if [ -n "$SANDBOX_LIST" ]; then
      echo "  Available sandboxes:"
      echo "$SANDBOX_LIST" | while read -r s; do echo "    - $s"; done
      echo ""
    fi
    echo -n "  Sandbox name: "
    read -r SANDBOX_NAME
  fi
fi

[ -z "$SANDBOX_NAME" ] && fail "No sandbox name provided."
info "Sandbox: $SANDBOX_NAME"

# ── Step 1b: Verify SSH connectivity ──────────────────────────────
info "Testing SSH connection to sandbox..."
SSH_TEST=$(ssh_sandbox "$SANDBOX_NAME" "echo OK" 2>/dev/null || echo "FAIL")
if [ "$SSH_TEST" != "OK" ]; then
  fail "Cannot SSH into sandbox '$SANDBOX_NAME'. Is it running?"
fi
ok "SSH connection verified"

# ── Step 2: Set interval ─────────────────────────────────────────
if [ -z "$INTERVAL" ]; then
  echo ""
  echo "  How often should the wakeup trigger?"
  echo ""
  echo "    1) Every 5 minutes"
  echo "    2) Every 10 minutes (recommended)"
  echo "    3) Every 15 minutes"
  echo "    4) Every 30 minutes"
  echo "    5) Every hour"
  echo "    6) Custom"
  echo ""
  echo -n "  Choice (1-6) [2]: "
  read -r CHOICE

  case "${CHOICE:-2}" in
    1) INTERVAL=5 ;;
    2) INTERVAL=10 ;;
    3) INTERVAL=15 ;;
    4) INTERVAL=30 ;;
    5) INTERVAL=60 ;;
    6)
      echo -n "  Minutes between wakeups: "
      read -r INTERVAL
      ;;
    *) INTERVAL=10 ;;
  esac
fi

[ -z "$INTERVAL" ] && INTERVAL=10
info "Interval: every $INTERVAL minutes"

# ── Step 3: Deploy skill ──────────────────────────────────────────
echo ""
info "Deploying NemoClaw Wakeup skill..."

SKILL_FILE="$SCRIPT_DIR/skill/SKILL.md"
if [ ! -f "$SKILL_FILE" ]; then
  fail "skill/SKILL.md not found in repo. Re-clone the repository."
fi

INSTALLED_AT="$(date +%Y-%m-%dT%H:%M:%S)"
ssh_sandbox "$SANDBOX_NAME" "mkdir -p $(dirname $SKILL_DEST)" 2>/dev/null || true
sed -e "s/__INTERVAL__/$INTERVAL/g" \
    -e "s/__INSTALLED_AT__/$INSTALLED_AT/g" \
    "$SKILL_FILE" | ssh_sandbox "$SANDBOX_NAME" "cat > $SKILL_DEST"
ok "Skill deployed (interval: every ${INTERVAL}m)"

# ── Step 4: Seed WAKEUP.md if missing ────────────────────────────
info "Checking for WAKEUP.md in sandbox..."

HB_EXISTS=$(ssh_sandbox "$SANDBOX_NAME" "[ -f $WAKEUP_MD_PATH ] && echo yes || echo no")

if [ "$HB_EXISTS" = "no" ]; then
  info "Seeding default WAKEUP.md..."

  ssh_sandbox "$SANDBOX_NAME" "cat > $WAKEUP_MD_PATH" << 'WKMD'
# Wakeup Instructions

This file is read by the OpenClaw agent every time the host-side wakeup
triggers. Edit these instructions to control what the agent does on each pulse.

## Current Tasks

1. Check my Gmail inbox for unread emails. Summarize any important messages.

## Rules

- Do NOT send emails or replies unless a rule below explicitly says to.
- Do NOT create calendar events unless instructed below.
- Do NOT send Telegram, Discord, or Slack messages unless instructed below.
- If there is nothing to do, simply end your turn with no output.
- Keep all output concise and within the session — do not deliver to channels.

## Auto-Reply Rules

(Add rules here if you want the agent to automatically reply to messages)

<!-- Example:
- Reply to emails from boss@company.com confirming receipt.
- Forward emails with "URGENT" in subject to backup@company.com.
-->
WKMD

  ok "Default WAKEUP.md deployed"
else
  ok "WAKEUP.md already exists in sandbox"
fi

# ── Step 5: Create wakeup.sh ─────────────────────────────────────
info "Installing wakeup script..."

mkdir -p "$INSTALL_DIR"

cat > "$INSTALL_DIR/wakeup.sh" << 'WKEOF'
#!/bin/bash
# NemoClaw Wakeup — fires the OpenClaw agent via SSH.
# Uses flock to prevent overlapping runs. Uses unique session IDs
# to prevent context bleed between pulses.

CONFIG="$HOME/.nemoclaw/wakeup/config.env"
source "$CONFIG" 2>/dev/null || {
  echo "$(date +%Y-%m-%dT%H:%M:%S) ERROR config.env missing" >> "$HOME/.nemoclaw/wakeup/wakeup.log"
  exit 1
}

LOG="$HOME/.nemoclaw/wakeup/wakeup.log"
LOCK="$HOME/.nemoclaw/wakeup/wakeup.lock"
MAX_LOG=1000

# ── Concurrency guard (flock) ────────────────────────────────────
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date +%Y-%m-%dT%H:%M:%S) SKIP previous wakeup still running" >> "$LOG"
  exit 0
fi

# ── Unique session ID ────────────────────────────────────────────
SESSION_ID="wakeup-$(date +%s)-$$"

# ── Agent message ────────────────────────────────────────────────
AGENT_MSG="NemoClaw Wakeup triggered. You MUST read the file /sandbox/.openclaw-data/workspace/WAKEUP.md right now and follow ONLY the instructions in that file. Do not use any cached or remembered instructions from previous sessions. Read the file fresh. Do not send messages to Telegram, Discord, or Slack unless WAKEUP.md explicitly tells you to."

echo "$(date +%Y-%m-%dT%H:%M:%S) START session=$SESSION_ID sandbox=$WAKEUP_SANDBOX" >> "$LOG"

# ── Fire agent via SSH (fire-and-forget with timeout) ────────────
ssh -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o GlobalKnownHostsFile=/dev/null \
    -o LogLevel=ERROR \
    -o ConnectTimeout=10 \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=4 \
    -o ProxyCommand="$WAKEUP_OPENSHELL ssh-proxy --gateway-name nemoclaw --name $WAKEUP_SANDBOX" \
    "sandbox@openshell-$WAKEUP_SANDBOX" \
    "openclaw agent --agent main --message \"$AGENT_MSG\" --session-id \"$SESSION_ID\"" >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "$(date +%Y-%m-%dT%H:%M:%S) DONE session=$SESSION_ID exit=0" >> "$LOG"
else
  echo "$(date +%Y-%m-%dT%H:%M:%S) FAIL session=$SESSION_ID exit=$EXIT_CODE" >> "$LOG"
fi

# ── Log rotation ─────────────────────────────────────────────────
LINES=$(wc -l < "$LOG" 2>/dev/null || echo 0)
if [ "$LINES" -gt "$MAX_LOG" ]; then
  tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
WKEOF

chmod +x "$INSTALL_DIR/wakeup.sh"
ok "Wakeup script: $INSTALL_DIR/wakeup.sh"

# ── Step 6: Save config ──────────────────────────────────────────
cat > "$INSTALL_DIR/config.env" << CFGEOF
WAKEUP_SANDBOX="$SANDBOX_NAME"
WAKEUP_INTERVAL="$INTERVAL"
WAKEUP_OPENSHELL="$OPENSHELL_BIN"
CFGEOF
ok "Config: $INSTALL_DIR/config.env"

# ── Step 7: Install cron job ─────────────────────────────────────
info "Setting up cron job..."

CRON_ENTRY="*/$INTERVAL * * * * $INSTALL_DIR/wakeup.sh  # nemoclaw-wakeup"

# Remove old heartbeat AND wakeup entries
EXISTING_CRON=$(crontab -l 2>/dev/null | grep -v "nemoclaw-wakeup" | grep -v "nemoclaw-heartbeat" || true)
if [ -n "$EXISTING_CRON" ]; then
  (echo "$EXISTING_CRON"; echo "$CRON_ENTRY") | crontab -
else
  echo "$CRON_ENTRY" | crontab -
fi

ok "Cron job installed (every $INTERVAL minutes)"

# ── Done ──────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  NemoClaw Wakeup installed!                             ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Sandbox:    $SANDBOX_NAME"
echo "  Interval:   every $INTERVAL minutes"
echo "  Trigger:    SSH (via openshell ssh-proxy, ~400ms)"
echo "  Log file:   $INSTALL_DIR/wakeup.log"
echo ""
echo "  The agent reads WAKEUP.md in the sandbox for its instructions."
echo "  To change what the agent does:"
echo ""
echo "    Via TUI or Telegram:"
echo "      \"Update my /sandbox/.openclaw-data/workspace/WAKEUP.md to also check my calendar\""
echo ""
echo "    Via SSH:"
echo "      openshell sandbox connect $SANDBOX_NAME"
echo "      nano /sandbox/.openclaw-data/workspace/WAKEUP.md"
echo ""
echo "  Commands:"
echo "    Test now:         $INSTALL_DIR/wakeup.sh"
echo "    View log:         tail -f $INSTALL_DIR/wakeup.log"
echo "    Check status:     ./install.sh --status"
echo "    Change interval:  ./install.sh --interval 30"
echo "    Uninstall:        ./install.sh --uninstall"
echo ""
