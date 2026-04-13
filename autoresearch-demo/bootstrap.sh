#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Bootstrap Slurm/SSH MCP access for a NemoClaw sandbox.
#
# Architecture (follows the Blender MCP demo pattern):
#   Host:    slurm-mcp (Python, holds SSH key) → mcp-proxy (HTTP/SSE)
#   Policy:  sandbox allowed to reach host mcp-proxy port
#   Sandbox: mcporter connects to mcp-proxy, agent gets 34 Slurm + SSH tools
#
# The SSH private key NEVER enters the sandbox.
#
# Usage:
#   ./ssh-skill/bootstrap.sh \
#     --sandbox <sandbox-name> \
#     --alias builder=<HOST_IP> \
#     [--key <path-to-ssh-private-key>] \
#     [--user <ssh-user>] \
#     [--user-root <remote-home>] \
#     [--port <ssh-port>] \
#     [--mcp-port <mcp-proxy-port>]

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -- Parse flags ---------------------------------------------------------------

SANDBOX=""
SSH_KEY=""
SSH_PASSWORD=""
SSH_PORT=22
SSH_USER=""
USER_ROOT=""
MCP_PORT=9878
ALIAS_NAME=""
ALIAS_HOST=""

usage() {
  echo "Usage: $0 \\"
  echo "         --sandbox <name> --alias <name>=<host> \\"
  echo "         [--key <path>] [--user <user>] [--user-root <path>]"
  echo "         [--port <port>] [--mcp-port <port>]"
  echo ""
  echo "  --sandbox    OpenShell sandbox name"
  echo "  --alias      SSH host alias (e.g. --alias builder=<HOST_IP>)"
  echo "  --key        Path to SSH private key (stays on host, never enters sandbox)"
  echo "  --password   SSH password (use --key OR --password, not both)"
  echo "  --user       SSH username"
  echo "  --user-root  Remote home/root directory (default: /home/<user>)"
  echo "  --port       SSH port (default: 22)"
  echo "  --mcp-port   Port for mcp-proxy on host (default: 9878)"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sandbox)   SANDBOX="$2";   shift 2 ;;
    --alias)
      ALIAS_NAME="${2%%=*}"
      ALIAS_HOST="${2#*=}"
      if [[ "$ALIAS_NAME" == "$2" || -z "$ALIAS_HOST" ]]; then
        echo "Error: --alias must be name=host (e.g. builder=<HOST_IP>)"
        exit 1
      fi
      shift 2 ;;
    --key)       SSH_KEY="$2";      shift 2 ;;
    --password)  SSH_PASSWORD="$2"; shift 2 ;;
    --user)      SSH_USER="$2";     shift 2 ;;
    --user-root) USER_ROOT="$2";    shift 2 ;;
    --port)      SSH_PORT="$2";     shift 2 ;;
    --mcp-port)  MCP_PORT="$2";     shift 2 ;;
    -h|--help)   usage ;;
    *)           echo "Unknown option: $1"; usage ;;
  esac
done

[[ -z "$SANDBOX" ]]    && echo "Error: --sandbox is required." && usage
[[ -z "$ALIAS_NAME" ]] && echo "Error: --alias is required." && usage

if [[ -n "$SSH_KEY" && ! -f "$SSH_KEY" ]]; then
  echo "Error: SSH key not found: $SSH_KEY"
  exit 1
fi

[[ -z "$USER_ROOT" && -n "$SSH_USER" ]] && USER_ROOT="/home/$SSH_USER"
[[ -z "$USER_ROOT" ]] && USER_ROOT="/home/\$USER"

# -- Pre-flight ----------------------------------------------------------------

for cmd in openshell uvx; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: '$cmd' not found."
    exit 1
  fi
done

if ! openshell sandbox get "$SANDBOX" &>/dev/null; then
  echo "Error: sandbox '$SANDBOX' not found or not running."
  exit 1
fi

echo "=== Slurm/SSH MCP bootstrap ==="
echo "  Sandbox:  $SANDBOX"
echo "  Target:   $ALIAS_NAME ($ALIAS_HOST)"
echo "  MCP port: $MCP_PORT"
echo "  Key:      ${SSH_KEY:-<none>} (stays on HOST)"
echo ""

# -- Step 1: Start slurm-mcp via mcp-proxy on host ----------------------------

echo "--- Step 1: mcp-proxy + slurm-mcp on host ---"

LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/nemoclaw-ssh-skill"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/mcp-proxy.log"
PID_FILE="$LOG_DIR/mcp-proxy.pid"

# Kill existing
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "  Stopping existing mcp-proxy (pid $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
fi

# Also kill anything on our port
EXISTING_PID=$(lsof -ti :$MCP_PORT 2>/dev/null || true)
if [[ -n "$EXISTING_PID" ]]; then
  kill "$EXISTING_PID" 2>/dev/null || true
  sleep 1
fi

# Create wrapper script with baked env (slurm-mcp reads config from env vars)
WRAPPER="$LOG_DIR/run-slurm-mcp.sh"
cat > "$WRAPPER" << EOF
#!/bin/bash
export SLURM_SSH_HOST=$ALIAS_HOST
export SLURM_SSH_PORT=$SSH_PORT
${SSH_USER:+export SLURM_SSH_USER=$SSH_USER}
${SSH_KEY:+export SLURM_SSH_KEY_PATH=$SSH_KEY}
${SSH_PASSWORD:+export SLURM_SSH_PASSWORD=$SSH_PASSWORD}
export SLURM_SSH_KNOWN_HOSTS=$HOME/.ssh/known_hosts
export SLURM_USER_ROOT=$USER_ROOT
export SLURM_COMMAND_TIMEOUT=120
exec uvx --from "git+https://github.com/yidong72/slurm_mcp.git" slurm-mcp
EOF
chmod +x "$WRAPPER"

echo "  Starting: mcp-proxy :$MCP_PORT → slurm-mcp → $ALIAS_HOST"
nohup uvx mcp-proxy --host 0.0.0.0 --port "$MCP_PORT" "$WRAPPER" \
  > "$LOG_FILE" 2>&1 &
MCP_PID=$!
echo "$MCP_PID" > "$PID_FILE"

echo -n "  Waiting"
for i in $(seq 1 15); do
  if lsof -ti :$MCP_PORT >/dev/null 2>&1 && kill -0 "$MCP_PID" 2>/dev/null; then
    echo " OK (pid $MCP_PID)"
    break
  fi
  if ! kill -0 "$MCP_PID" 2>/dev/null; then
    echo " FAILED"
    tail -5 "$LOG_FILE" 2>/dev/null
    exit 1
  fi
  echo -n "."
  sleep 1
done

# -- Step 2: Network policy ----------------------------------------------------

echo ""
echo "--- Step 2: Network policy ---"

# Get the Docker bridge IP that reaches the host (where mcp-proxy listens)
HOST_IP=$(openshell sandbox exec -n "$SANDBOX" -- bash -c 'getent hosts host.openshell.internal | awk "{print \$1}"' 2>/dev/null)
if [[ -z "$HOST_IP" ]]; then
  HOST_IP="172.29.0.254"
  echo "  Warning: could not resolve host.openshell.internal, using $HOST_IP"
fi

POLICY_FILE=$(mktemp /tmp/nemoclaw-mcp-policy-XXXXXX.yaml)
CURRENT=$(openshell policy get --full "$SANDBOX" 2>/dev/null | awk '/^---/{found=1; next} found{print}')

python3 -c "
import re, sys
current = sys.stdin.read()
port = int(sys.argv[1])
host_ip = sys.argv[2]

# Remove any previous ssh_mcp or ssh_remote block
current = re.sub(r'  ssh_(mcp|remote):.*?(?=\n  \w|\Z)', '', current, flags=re.DOTALL)

block = f'''  ssh_mcp:
    name: ssh_mcp
    endpoints:
    - host: \"{host_ip}\"
      port: {port}
      access: full
    binaries:
    - path: /usr/local/bin/node*
    - path: /usr/bin/node*
    - path: /usr/bin/curl*
    - path: /bin/bash*'''

result = current.rstrip() + '\n' + block + '\n'
print(result)
" "$MCP_PORT" "$HOST_IP" <<< "$CURRENT" > "$POLICY_FILE"

openshell policy set --policy "$POLICY_FILE" --wait "$SANDBOX"
rm -f "$POLICY_FILE"
echo "  Allowed: sandbox → $HOST_IP:$MCP_PORT"

# -- Step 3: mcporter in sandbox -----------------------------------------------

echo ""
echo "--- Step 3: mcporter ---"

if openshell sandbox exec -n "$SANDBOX" -- bash -c 'test -f /sandbox/node_modules/mcporter/dist/cli.js' 2>/dev/null; then
  echo "  mcporter already installed"
else
  echo "  Installing mcporter..."
  openshell sandbox exec -n "$SANDBOX" -- bash -c 'mkdir -p /sandbox/bin && cd /sandbox && npm install --prefix /sandbox mcporter 2>&1 | tail -2 && printf "#!/bin/bash\nexec node /sandbox/node_modules/mcporter/dist/cli.js \"\$@\"\n" > /sandbox/bin/mcporter && chmod +x /sandbox/bin/mcporter'
fi

# -- Step 4: mcporter config ---------------------------------------------------

echo ""
echo "--- Step 4: mcporter config ---"

MCPORTER_CONFIG="{\"mcpServers\":{\"$ALIAS_NAME\":{\"type\":\"http\",\"baseUrl\":\"http://$HOST_IP:$MCP_PORT/sse\"}}}"
openshell sandbox exec -n "$SANDBOX" -- bash -c "mkdir -p ~/.mcporter && echo '$MCPORTER_CONFIG' > ~/.mcporter/mcporter.json"
echo "  Server '$ALIAS_NAME' → http://$HOST_IP:$MCP_PORT/sse"

openshell sandbox exec -n "$SANDBOX" -- bash -c 'grep -q "/sandbox/bin" /sandbox/.bashrc 2>/dev/null || echo "export PATH=\"/sandbox/bin:\$PATH\"" >> /sandbox/.bashrc'

# -- Step 5: Skill file --------------------------------------------------------

echo ""
echo "--- Step 5: Agent skill ---"

SKILL_UPLOAD=$(mktemp -d /tmp/nemoclaw-ssh-skill-XXXXXX)
cat > "$SKILL_UPLOAD/SKILL.md" << SKILLEOF
---
name: ssh-remote
description: "Run commands on remote server '${ALIAS_NAME}' (${ALIAS_HOST}). Use this skill whenever the user asks to do anything on ${ALIAS_NAME}."
---

# Remote Server: ${ALIAS_NAME}

Run shell commands on ${ALIAS_NAME} using \`/sandbox/bin/mcporter\`.
This is a bash command — run it in the terminal. Do NOT install any MCP libraries.

## How to run a command on ${ALIAS_NAME}

\`\`\`bash
/sandbox/bin/mcporter call ${ALIAS_NAME}.run_shell_command command="<your command here>"
\`\`\`

That's it. Just run that in the terminal. Examples:

\`\`\`bash
/sandbox/bin/mcporter call ${ALIAS_NAME}.run_shell_command command="hostname"
/sandbox/bin/mcporter call ${ALIAS_NAME}.run_shell_command command="nvidia-smi"
/sandbox/bin/mcporter call ${ALIAS_NAME}.run_shell_command command="ls -la /home/${SSH_USER:-$USER}"
/sandbox/bin/mcporter call ${ALIAS_NAME}.run_shell_command command="cd /workspace && python train.py --lr 0.001"
\`\`\`

## Other available tools

All called the same way — \`/sandbox/bin/mcporter call ${ALIAS_NAME}.<tool> <args>\`:

| Tool | What it does |
|------|-------------|
| \`run_shell_command\` | Run any shell command |
| \`get_gpu_availability\` | Check free GPUs |
| \`get_cluster_status\` | Slurm partitions and nodes |
| \`submit_job\` | Submit Slurm batch job |
| \`list_jobs\` | List running/pending jobs |
| \`get_job_details\` | Job details by ID |
| \`cancel_job\` | Cancel a job |
| \`list_directory\` | List remote directory |
| \`read_file\` | Read a remote file |
| \`write_file\` | Write a remote file |
| \`find_files\` | Search for files |

## Important

- \`mcporter\` is already installed at \`/sandbox/bin/mcporter\` — do NOT install anything
- Run it as a bash command in the terminal — it is NOT a Python library
- Commands run as user \`${SSH_USER:-$USER}\` on ${ALIAS_NAME} (${ALIAS_HOST})
- Timeout: 120s — for long jobs use \`submit_job\` instead of \`run_shell_command\`
SKILLEOF

openshell sandbox upload "$SANDBOX" "$SKILL_UPLOAD" /sandbox/.hermes-data/skills/ssh-remote
rm -rf "$SKILL_UPLOAD"
echo "  Uploaded to /sandbox/.hermes-data/skills/ssh-remote"

# -- Step 6: Verify ------------------------------------------------------------

echo ""
echo "--- Verify ---"

RESULT=$(openshell sandbox exec -n "$SANDBOX" -- bash -c '/sandbox/bin/mcporter call '"$ALIAS_NAME"'.run_shell_command command="hostname" 2>&1' 2>&1)

if echo "$RESULT" | grep -q "builder\|$ALIAS_HOST"; then
  echo "  mcporter call $ALIAS_NAME.run_shell_command command=\"hostname\" → OK"
  echo "$RESULT" | grep -v "Warning\|UNDICI"
else
  echo "  Result: $RESULT"
  echo "  Check: $LOG_FILE"
fi

# -- Done ----------------------------------------------------------------------

echo ""
echo "=== Slurm/SSH MCP ready ==="
echo ""
echo "  Sandbox:    $SANDBOX"
echo "  Target:     $ALIAS_NAME ($ALIAS_HOST)"
echo "  MCP proxy:  localhost:$MCP_PORT (pid $MCP_PID)"
echo "  Log:        $LOG_FILE"
echo "  Tools:      34 (Slurm + SSH + files)"
echo "  SSH key:    ON HOST ONLY"
echo ""
echo "  To stop:  kill \$(cat $PID_FILE)"
echo "  To restart: $0 $*"
