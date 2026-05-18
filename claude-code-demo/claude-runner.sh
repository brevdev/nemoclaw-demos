#!/bin/bash
# Runner script for Claude Code inside NemoClaw sandbox.
#
# Modes:
#   Foreground (default): blocks until Claude Code finishes
#   --background:         starts Claude Code in background, returns immediately
#   --status [project]:   check if a build is running/finished
#   --status-all:         show status of all recent builds
#   --result [project]:   show the result summary of a finished build
#   --print:              one-shot mode (no project context)
#   --continue:           resume previous session

PROJECTS_DIR="/sandbox/claude-projects"
LOG_DIR="/sandbox/.config/claude-code/logs"
STATUS_DIR="/sandbox/.config/claude-code/status"
CONFIG="/sandbox/.config/claude-code/config.json"
CLAUDE_BIN="/sandbox/.config/claude-code/node_modules/.bin/claude"
mkdir -p "$LOG_DIR" "$STATUS_DIR"

# ── Status check mode ────────────────────────────────────────────
if [ "${1:-}" = "--status-all" ]; then
  echo "=== Claude Code Build Status ==="
  found=false
  for sf in "$STATUS_DIR"/*.json; do
    [ -f "$sf" ] || continue
    found=true
    python3 -c "
import json, os
d = json.load(open('$sf'))
name = d.get('project','?')
status = d.get('status','?')
started = d.get('started_at','?')
icon = '🔨' if status == 'running' else ('✅' if status == 'done' else '❌')
pid = d.get('pid','')
if status == 'running' and pid:
    alive = os.path.exists(f'/proc/{pid}')
    if not alive:
        status = 'done (process ended)'
        icon = '✅'
print(f'{icon} {name}: {status} (started {started})')
" 2>/dev/null
  done
  [ "$found" = false ] && echo "No builds found."
  exit 0
fi

if [ "${1:-}" = "--status" ]; then
  PROJECT="${2:-}"
  if [ -z "$PROJECT" ]; then
    LATEST=$(ls -t "$STATUS_DIR"/*.json 2>/dev/null | head -1)
    [ -z "$LATEST" ] && { echo "No builds found."; exit 0; }
  else
    LATEST="$STATUS_DIR/${PROJECT}.json"
  fi
  if [ ! -f "$LATEST" ]; then
    echo "No build status found for '$PROJECT'."
    exit 1
  fi
  python3 -c "
import json, os
d = json.load(open('$LATEST'))
name = d.get('project','?')
status = d.get('status','?')
started = d.get('started_at','?')
pid = d.get('pid','')
logfile = d.get('logfile','')
exit_code = d.get('exit_code','')
if status == 'running' and pid:
    if not os.path.exists(f'/proc/{pid}'):
        status = 'done'
print(f'Project:  {name}')
print(f'Status:   {status}')
print(f'Started:  {started}')
if exit_code != '': print(f'Exit:     {exit_code}')
if logfile: print(f'Log:      {logfile}')
if status == 'done' and logfile and os.path.exists(logfile):
    lines = open(logfile).readlines()
    last = [l.strip() for l in lines[-20:] if l.strip()]
    if last:
        print()
        print('Last output:')
        for l in last[-10:]:
            print(f'  {l}')
" 2>/dev/null
  exit 0
fi

if [ "${1:-}" = "--result" ]; then
  PROJECT="${2:-}"
  if [ -z "$PROJECT" ]; then
    LATEST=$(ls -t "$STATUS_DIR"/*.json 2>/dev/null | head -1)
    [ -z "$LATEST" ] && { echo "No builds found."; exit 0; }
    PROJECT=$(python3 -c "import json; print(json.load(open('$LATEST')).get('project',''))" 2>/dev/null)
  fi
  PROJ_PATH="$PROJECTS_DIR/$PROJECT"
  if [ ! -d "$PROJ_PATH" ]; then
    echo "Project '$PROJECT' not found."
    exit 1
  fi
  echo "=== Project: $PROJECT ==="
  echo ""
  echo "Files:"
  find "$PROJ_PATH" -type f -not -path '*/.git/*' -not -path '*/node_modules/*' | sort | head -30
  echo ""
  FILE_COUNT=$(find "$PROJ_PATH" -type f -not -path '*/.git/*' -not -path '*/node_modules/*' | wc -l)
  echo "Total files: $FILE_COUNT"
  if [ -f "$PROJ_PATH/README.md" ]; then
    echo ""
    echo "=== README.md ==="
    head -30 "$PROJ_PATH/README.md"
  fi
  exit 0
fi

# ── Setup environment ─────────────────────────────────────────────
# Claude Code authenticates via a short-lived OAuth access token pushed
# in from the host by claude-push-daemon.py.  The refresh token never
# enters the sandbox.  If the token file is missing we fall back to
# whatever the CLI finds on its own (useful for apikey mode).
export DISABLE_AUTOUPDATER=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

CLAUDE_TOKEN_FILE="/sandbox/.openclaw-data/claude-code/oauth_token"
if [ -s "$CLAUDE_TOKEN_FILE" ]; then
  # tr -d to strip any trailing newline the daemon might have written
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '\n\r' < "$CLAUDE_TOKEN_FILE")"
  export CLAUDE_CODE_OAUTH_TOKEN
fi

# Load GitHub proxy if configured (for git push via forward proxy, like Planet)
# Git URL rewrite: https://github.com/ → http://<host>:9203/
# Traffic flows through the OpenShell transparent proxy → policy check → host proxy → GitHub
if [ -f /sandbox/.config/claude-code/proxy.env ]; then
  source /sandbox/.config/claude-code/proxy.env
  if [ -n "$GITHUB_PROXY_URL" ]; then
    git config --global url."${GITHUB_PROXY_URL}/".insteadOf "https://github.com/" 2>/dev/null || true
    git config --global http.sslCAInfo /etc/openshell-tls/ca-bundle.pem 2>/dev/null || true
    if [ -n "${GITHUB_PROXY_TOKEN:-}" ]; then
      git config --global http."${GITHUB_PROXY_URL}/".extraHeader "X-Proxy-Token: ${GITHUB_PROXY_TOKEN}" 2>/dev/null || true
    fi
  fi
fi

APPROVAL_MODE="auto_approve"
if [ -f "$CONFIG" ]; then
  SAVED=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('approval_mode',''))" 2>/dev/null || true)
  [ -n "$SAVED" ] && APPROVAL_MODE="$SAVED"
fi

# ── Parse arguments ───────────────────────────────────────────────
PROJECT=""
PROMPT=""
PRINT_MODE=false
CONTINUE_MODE=false
BACKGROUND=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)    PROJECT="$2"; shift 2 ;;
    --prompt)     PROMPT="$2"; shift 2 ;;
    --print)      PRINT_MODE=true; shift ;;
    --continue)   CONTINUE_MODE=true; shift ;;
    --background) BACKGROUND=true; shift ;;
    *) PROMPT="$*"; break ;;
  esac
done

if [ -z "$PROMPT" ] && [ "$CONTINUE_MODE" = false ]; then
  echo "Usage: claude-runner.sh --project <name> --prompt '<description>' [--background]"
  echo "       claude-runner.sh --status [project]"
  echo "       claude-runner.sh --status-all"
  echo "       claude-runner.sh --result [project]"
  exit 1
fi

[ -z "$PROJECT" ] && PROJECT="project-$(date +%s)"

PROJECT_PATH="$PROJECTS_DIR/$PROJECT"
mkdir -p "$PROJECT_PATH"
LOGFILE="$LOG_DIR/${PROJECT}-$(date +%Y%m%d-%H%M%S).log"
STATUS_FILE="$STATUS_DIR/${PROJECT}.json"

APPROVE_FLAGS=""
if [ "$APPROVAL_MODE" = "auto_approve" ]; then
  APPROVE_FLAGS="--dangerously-skip-permissions"
fi

cd "$PROJECT_PATH"

# ── Background mode ───────────────────────────────────────────────
if [ "$BACKGROUND" = true ]; then
  STARTED_AT=$(date +%Y-%m-%dT%H:%M:%S)

  _PROMPT="$PROMPT" _PROJECT="$PROJECT" _STARTED="$STARTED_AT" \
  _LOGFILE="$LOGFILE" _SF="$STATUS_FILE" \
  python3 -c "
import json, os
json.dump({
  'project': os.environ['_PROJECT'],
  'status': 'running',
  'started_at': os.environ['_STARTED'],
  'logfile': os.environ['_LOGFILE'],
  'prompt': os.environ['_PROMPT'][:200],
  'pid': '',
  'exit_code': ''
}, open(os.environ['_SF'], 'w'), indent=2)
"

  if [ "$CONTINUE_MODE" = true ]; then
    nohup $CLAUDE_BIN $APPROVE_FLAGS --continue > "$LOGFILE" 2>&1 &
  else
    nohup $CLAUDE_BIN $APPROVE_FLAGS -p "$PROMPT" > "$LOGFILE" 2>&1 &
  fi
  BG_PID=$!

  _SF="$STATUS_FILE" _PID="$BG_PID" python3 -c "
import json, os
sf = os.environ['_SF']
d = json.load(open(sf))
d['pid'] = os.environ['_PID']
json.dump(d, open(sf, 'w'), indent=2)
"

  # Background watcher: updates status file and notifies via the gateway
  # when Claude Code finishes. Uses openclaw agent --deliver so the message
  # routes through the gateway to whatever channel the user is on.
  (
    wait $BG_PID 2>/dev/null
    FINISHED_AT=$(date +%Y-%m-%dT%H:%M:%S)
    FILE_COUNT=$(find "$PROJECT_PATH" -type f -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null | wc -l)
    [ "$FILE_COUNT" -gt 0 ] && REAL_EC=0 || REAL_EC=1

    _SF="$STATUS_FILE" _EC="$REAL_EC" _FC="$FILE_COUNT" _FIN="$FINISHED_AT" \
    python3 -c "
import json, os
sf = os.environ['_SF']
d = json.load(open(sf))
d['status'] = 'done'
d['exit_code'] = os.environ['_EC']
d['file_count'] = int(os.environ['_FC'])
d['finished_at'] = os.environ['_FIN']
json.dump(d, open(sf, 'w'), indent=2)
" 2>/dev/null

    # Notify the user through the gateway agent
    if [ "$FILE_COUNT" -gt 0 ]; then
      NOTIFY_MSG="Claude Code finished building $PROJECT ($FILE_COUNT files). Run: claude-runner.sh --result $PROJECT"
    else
      NOTIFY_MSG="Claude Code build for $PROJECT finished with errors. Run: claude-runner.sh --status $PROJECT"
    fi
    /usr/local/bin/openclaw agent --agent main --channel last --deliver \
      -m "$NOTIFY_MSG" 2>/dev/null || true
  ) &

  echo "BACKGROUND_STARTED"
  echo "project=$PROJECT"
  echo "pid=$BG_PID"
  echo "log=$LOGFILE"
  echo "status_file=$STATUS_FILE"
  echo "Check progress: claude-runner.sh --status $PROJECT"
  exit 0
fi

# ── Foreground mode ───────────────────────────────────────────────
if [ "$CONTINUE_MODE" = true ]; then
  exec $CLAUDE_BIN $APPROVE_FLAGS --continue 2>&1 | tee "$LOGFILE"
elif [ "$PRINT_MODE" = true ]; then
  exec $CLAUDE_BIN -p "$PROMPT" 2>&1 | tee "$LOGFILE"
else
  exec $CLAUDE_BIN $APPROVE_FLAGS -p "$PROMPT" 2>&1 | tee "$LOGFILE"
fi
