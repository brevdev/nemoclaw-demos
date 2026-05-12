#!/usr/bin/env bash
# =============================================================================
# AI Teaching Assistant — Full Install Script
#
# Sets up the complete stack:
#   1. TA environment  (Docker via make up — always includes the RAG stack)
#   2. MCP server      (host Python process on port 8999)
#   3. OpenShell skill (sandbox upload + venv + config.json)
#
# Idempotent — each step checks whether it is already done before acting.
# Usage:
#   bash install.sh [--fresh] [sandbox-name]
#
#   --fresh    Wipe all user data before starting (make fresh).
#   sandbox-name  Target sandbox (auto-detected when only one exists).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CREDS_PATH="$HOME/.nemoclaw/credentials.json"
MCP_PORT=8999
MCP_PID_FILE="/tmp/ta-mcp.pid"
MCP_LOG_FILE="/tmp/ta-mcp.log"
SKILL_NAME="ai-teaching-assistant-skills"
SKILL_SRC="$SCRIPT_DIR/ai_teaching_assistant_skills"
SANDBOX_SKILL_ROOT="/sandbox/.openclaw/workspace/skills/$SKILL_NAME"

# ── Parse flags ───────────────────────────────────────────────────────────────
USE_FRESH=false
SANDBOX_ARG=""

for arg in "$@"; do
  case "$arg" in
    --fresh) USE_FRESH=true ;;
    -*)      echo "Unknown flag: $arg  (valid: --fresh)" >&2; exit 1 ;;
    *)       SANDBOX_ARG="$arg" ;;
  esac
done

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()  { echo -e "${CYAN}  ▸ $*${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $*${NC}"; }
fail()  { echo -e "${RED}  ✗ $*${NC}"; exit 1; }
step()  { echo ""; echo -e "${CYAN}━━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║  AI Teaching Assistant — Full Stack Installer            ║${NC}"
echo -e "${CYAN}  ║  AgenticTA  +  MCP Server  +  OpenShell Skill           ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Mode  : ${GREEN}Full stack — agenticta + RAG (mandatory)${NC}"
$USE_FRESH && echo -e "  Fresh : ${YELLOW}yes — user data will be wiped${NC}"
echo ""

# =============================================================================
# STEP 0 — Clean up stale MCP server process
# =============================================================================
step "Step 0 — Clean up stale MCP server"

if [ -f "$MCP_PID_FILE" ]; then
  OLD_PID=$(cat "$MCP_PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    ok "Stopped existing MCP server (PID $OLD_PID)"
  fi
  rm -f "$MCP_PID_FILE"
fi

STALE=$(pgrep -f "ai_teaching_assistant_mcp_server" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  kill $STALE 2>/dev/null || true
  ok "Killed stale MCP server process(es)"
fi
ok "Environment clean"

# =============================================================================
# STEP 1 — Prerequisites
# =============================================================================
step "Step 1 — Prerequisites"

command -v docker    >/dev/null 2>&1 || fail "docker not found. Install Docker first."
docker info          >/dev/null 2>&1 || fail "Docker daemon is not running. Start Docker and retry."
# Compose v2 must be present as a docker CLI plugin — `make up` later runs
# `docker compose up -d`.  Without the plugin docker parses the args as
# `docker -d ...` and aborts with a cryptic "unknown shorthand flag" error.
# Auto-install via apt (Ubuntu/Debian) if missing; otherwise fail with a
# manual-install hint.
if ! docker compose version >/dev/null 2>&1; then
  warn "docker compose v2 plugin not found — installing..."
  if command -v apt-get >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null || [ "$(id -u)" = "0" ]; then
      sudo apt-get update -qq \
        && sudo apt-get install -y -qq docker-compose-plugin \
        || fail "apt-get install docker-compose-plugin failed. Install manually and retry."
    else
      info "sudo password required to install docker-compose-plugin..."
      sudo apt-get update -qq \
        && sudo apt-get install -y -qq docker-compose-plugin \
        || fail "apt-get install docker-compose-plugin failed. Install manually and retry."
    fi
  else
    fail "docker compose v2 plugin missing and no apt-get available. \
Install manually — see https://docs.docker.com/compose/install/linux/"
  fi
  docker compose version >/dev/null 2>&1 \
    || fail "docker compose still not callable after install. \
Check that /usr/libexec/docker/cli-plugins/docker-compose exists and is executable."
  ok "docker-compose-plugin installed"
fi
command -v make      >/dev/null 2>&1 || fail "make not found."
command -v python3   >/dev/null 2>&1 || fail "python3 not found."
command -v openshell >/dev/null 2>&1 || fail "openshell CLI not found. Is NemoClaw installed?"
command -v nemoclaw  >/dev/null 2>&1 || fail "nemoclaw CLI not found. Is NemoClaw installed?"

if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv install failed. Add ~/.local/bin to PATH and retry."
  ok "uv installed"
fi

ok "Docker       : $(docker --version | head -1)"
ok "Compose v2   : $(docker compose version --short 2>/dev/null || echo 'found')"
ok "Python       : $(python3 --version)"
ok "uv           : $(uv --version)"
ok "openshell    : $(openshell --version 2>/dev/null | head -1 || echo 'found')"

# =============================================================================
# STEP 2 — TA Environment (Docker stack)
# =============================================================================
step "Step 2 — TA Environment (Docker)"

cd "$SCRIPT_DIR"

_ta_api_up() {
  curl -sf --max-time 3 "http://localhost:8000/" >/dev/null 2>&1
}

_container_running() {
  docker ps --filter "name=agenticta" --filter "status=running" --format "{{.Names}}" 2>/dev/null \
    | grep -q "agenticta"
}

# ── 2a. Ensure RAG blueprint and cloud .env are ready (always) ───────────────
RAG_COMPOSE_DIR="$SCRIPT_DIR/rag/deploy/compose"

# Clone NVIDIA-AI-Blueprints/rag if compose files are missing
if [ ! -f "$RAG_COMPOSE_DIR/vectordb.yaml" ]; then
  info "RAG blueprint not found — cloning NVIDIA-AI-Blueprints/rag..."
  command -v git >/dev/null 2>&1 || fail "git not found. Install git and retry."
  # Remove stale incomplete rag/ dir (no .git inside) before fresh clone
  if [ -d "$SCRIPT_DIR/rag" ] && [ ! -d "$SCRIPT_DIR/rag/.git" ]; then
    rm -rf "$SCRIPT_DIR/rag"
  fi
  git clone https://github.com/NVIDIA-AI-Blueprints/rag.git "$SCRIPT_DIR/rag" \
    || fail "Failed to clone NVIDIA-AI-Blueprints/rag. Check network connectivity."
  ok "RAG blueprint cloned → rag/"
else
  ok "RAG blueprint present"
fi

# Always read the NGC key from the root .env (authoritative source)
_ngc_key=$(grep "^NGC_API_KEY=" "$SCRIPT_DIR/.env" | cut -d= -f2 | awk '{print $1}')
[ -n "$_ngc_key" ] || fail "NGC_API_KEY not set in root .env — required to pull the NVIDIA-AI-Blueprints/rag Docker images from nvcr.io"
_prompt_yaml="$SCRIPT_DIR/rag/src/nvidia_rag/rag_server/prompt.yaml"
[ -f "$_prompt_yaml" ] || fail "Expected prompt.yaml not found at $_prompt_yaml"

  # Build rag/deploy/compose/.env from nvdev.env if it is missing OR if it
  # does not contain a resolved NGC_API_KEY value (e.g. it still has the
  # repo's unresolved '${NGC_API_KEY}' reference).
  _rag_env_ok=false
  if [ -f "$RAG_COMPOSE_DIR/.env" ] && \
     grep -q "^export NGC_API_KEY=nvapi\|^NGC_API_KEY=nvapi" "$RAG_COMPOSE_DIR/.env" 2>/dev/null; then
    _rag_env_ok=true
  fi

  if ! $_rag_env_ok; then
    info "Creating rag/deploy/compose/.env (cloud endpoints via nvdev.env)..."
    {
      echo "export NGC_API_KEY=${_ngc_key}"
      cat "$RAG_COMPOSE_DIR/nvdev.env"
      printf '\n'  # nvdev.env may lack a trailing newline — guard before PROMPT_CONFIG_FILE
      echo "export PROMPT_CONFIG_FILE=${_prompt_yaml}"
    } > "$RAG_COMPOSE_DIR/.env"
    ok "rag/deploy/compose/.env created (cloud API endpoints)"
  else
    ok "rag/deploy/compose/.env present"
  fi

  # ── Always verify PROMPT_CONFIG_FILE is on its own line ──────────────────────
  # nvdev.env does not end with a newline, so a plain 'echo' appends
  # PROMPT_CONFIG_FILE directly to the last comment line — Docker Compose then
  # treats the whole thing as a comment and the variable is silently empty,
  # causing an 'invalid mount path: :' error in the ingestor container.
  # This block is idempotent: fixes both freshly-created and pre-existing files.
  if ! grep -qE "^(export )?PROMPT_CONFIG_FILE=/" "$RAG_COMPOSE_DIR/.env" 2>/dev/null; then
    # Strip any broken in-line occurrence, then re-add on its own line
    sed -i 's/export PROMPT_CONFIG_FILE=[^[:space:]]*//' "$RAG_COMPOSE_DIR/.env" 2>/dev/null || true
    printf '\nexport PROMPT_CONFIG_FILE=%s\n' "${_prompt_yaml}" >> "$RAG_COMPOSE_DIR/.env"
    ok "RAG .env: PROMPT_CONFIG_FILE corrected"
  fi

  # ── CPU-only: patch Milvus so it runs without a GPU ──────────────────────────
  # Docker Compose merge semantics cannot clear a 'devices' list via an override
  # file (devices: [] is a no-op).  On CPU-only hosts we must patch vectordb.yaml
  # directly to remove the GPU device reservation, then set the CPU image tag and
  # disable GPU search/index in the RAG .env.
  if ! nvidia-smi >/dev/null 2>&1; then
    _VECTORDB_YAML="$RAG_COMPOSE_DIR/vectordb.yaml"
    # Only patch if the GPU deploy block is still present (idempotent)
    if grep -q "^    deploy:" "$_VECTORDB_YAML" 2>/dev/null; then
      info "No GPU detected — patching vectordb.yaml to remove GPU device reservation..."
      python3 - "$_VECTORDB_YAML" <<'PYEOF'
import sys, re
path = sys.argv[1]
with open(path) as f:
    content = f.read()
# Remove the deploy/resources/reservations/devices block (GPU-only section).
# It sits at 4-space indent, immediately before the "profiles:" line.
patched = re.sub(
    r'\n    deploy:\n      resources:\n        reservations:\n          devices:\n(?:            [^\n]*\n)+',
    '\n',
    content
)
if patched != content:
    with open(path, 'w') as f:
        f.write(patched)
    print("  Removed GPU deploy block from milvus service")
else:
    print("  Deploy block not found — nothing to patch")
PYEOF
      ok "vectordb.yaml: GPU deploy block removed"
    else
      ok "vectordb.yaml: already CPU-patched"
    fi

    # Append CPU-specific Milvus settings to RAG .env (idempotent)
    _rag_env="$RAG_COMPOSE_DIR/.env"
    grep -q "MILVUS_VERSION" "$_rag_env" 2>/dev/null \
      || echo "export MILVUS_VERSION=v2.6.5" >> "$_rag_env"
    grep -q "APP_VECTORSTORE_ENABLEGPUSEARCH" "$_rag_env" 2>/dev/null \
      || echo "export APP_VECTORSTORE_ENABLEGPUSEARCH=False" >> "$_rag_env"
    grep -q "APP_VECTORSTORE_ENABLEGPUINDEX" "$_rag_env" 2>/dev/null \
      || echo "export APP_VECTORSTORE_ENABLEGPUINDEX=False" >> "$_rag_env"
    ok "RAG .env: CPU Milvus settings appended"

    # Stage cpu-override.yaml into the RAG compose dir — `make up` includes it
    # via `-f rag/deploy/compose/cpu-override.yaml` on CPU hosts, so it must
    # exist at that path or docker compose aborts before starting any service.
    _cpu_override_src="$SCRIPT_DIR/cpu-override.yaml"
    _cpu_override_dst="$RAG_COMPOSE_DIR/cpu-override.yaml"
    if [ ! -f "$_cpu_override_src" ]; then
      fail "cpu-override.yaml not found at $_cpu_override_src — required for CPU-only hosts"
    fi
    if [ ! -f "$_cpu_override_dst" ] || ! cmp -s "$_cpu_override_src" "$_cpu_override_dst"; then
      cp "$_cpu_override_src" "$_cpu_override_dst"
      ok "cpu-override.yaml staged → $_cpu_override_dst"
    else
      ok "cpu-override.yaml already staged"
    fi
  fi

# Log in to nvcr.io using the key from root .env (always fresh, avoids
# stale/unresolved values in the RAG .env)
if echo "$_ngc_key" | docker login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null 2>&1; then
  ok "Logged in to nvcr.io"
else
  fail "docker login nvcr.io failed — verify NGC_API_KEY in root .env has NGC registry access"
fi

# ── 2b. Check / start the Docker stack ───────────────────────────────────────
# Skip make up only when the container is running AND --fresh was NOT requested.
# With --fresh we always go through make fresh to wipe + restart cleanly.
if _container_running && ! $USE_FRESH; then
  ok "agenticta container already running — skipping make up"
  # The in-container FastAPI/Gradio processes are launched by `make up`, not by
  # the container start — if they died (or never started), the API health wait
  # below will time out.  Re-launch them when the API is not responding.
  if ! _ta_api_up; then
    info "TA API not responding inside the running container — starting FastAPI + Gradio"
    make api    || fail "make api failed.    Check: make logs-api"
    make gradio || fail "make gradio failed. Check: make logs-gradio"
  else
    ok "TA API already responding"
  fi
  # RAG services may not be running even when agenticta is — start them if needed
  if ! curl -sf --max-time 3 "http://localhost:8082/v1/health" >/dev/null 2>&1; then
    info "RAG services not running — starting with make rag-up"
    make rag-up || fail "make rag-up failed. Check: make rag-health"
  else
    ok "RAG services already running"
  fi
else
  if $USE_FRESH; then
    info "Running: make fresh"
    make fresh
  else
    info "Running: make up"
    make up
  fi
fi

# ── 2b. Wait for TA API (port 8000) ──────────────────────────────────────────
info "Waiting for TA API (localhost:8000)..."
TA_UP=false
for i in $(seq 1 30); do
  if _ta_api_up; then
    TA_UP=true; break
  fi
  sleep 2
done
$TA_UP || fail "TA API did not come up after 60 s. Check: make logs-api"
ok "TA API is healthy (http://localhost:8000)"

# ── 2c. Wait for RAG services ────────────────────────────────────────────────
info "Waiting for ingestor (localhost:8082)..."
INGESTOR_UP=false
for i in $(seq 1 30); do
  curl -sf --max-time 3 "http://localhost:8082/v1/health" >/dev/null 2>&1 \
    && INGESTOR_UP=true && break
  sleep 2
done
$INGESTOR_UP || fail "Ingestor did not come up. Check: make logs"

info "Waiting for RAG server (localhost:8081)..."
RAG_UP=false
for i in $(seq 1 30); do
  curl -sf --max-time 3 "http://localhost:8081/v1/health" >/dev/null 2>&1 \
    && RAG_UP=true && break
  sleep 2
done
$RAG_UP || fail "RAG server did not come up. Check: make logs"

ok "Ingestor    : http://localhost:8082"
ok "RAG server  : http://localhost:8081"

# =============================================================================
# STEP 2b — Build Study Break Games SPA
# =============================================================================
step "Step 2b — Build Study Break Games SPA"

GAMES_DIR="$SCRIPT_DIR/StudyBreakGames"
GAMES_DIST="$GAMES_DIR/dist"

if [ -d "$GAMES_DIST" ] && [ -f "$GAMES_DIST/index.html" ]; then
  ok "StudyBreakGames dist/ already built — skipping"
else
  if command -v npm >/dev/null 2>&1; then
    info "Installing StudyBreakGames dependencies (npm ci)..."
    (cd "$GAMES_DIR" && npm ci --silent) \
      || fail "npm ci failed in StudyBreakGames/"
    info "Building StudyBreakGames (npm run build)..."
    (cd "$GAMES_DIR" && npm run build) \
      && ok "StudyBreakGames built → $GAMES_DIST" \
      || fail "StudyBreakGames build failed. Check StudyBreakGames/ for errors."
  elif command -v bun >/dev/null 2>&1; then
    info "Installing StudyBreakGames dependencies (bun install)..."
    (cd "$GAMES_DIR" && bun install --frozen-lockfile) \
      || fail "bun install failed in StudyBreakGames/"
    info "Building StudyBreakGames (bun run build)..."
    (cd "$GAMES_DIR" && bun run build) \
      && ok "StudyBreakGames built → $GAMES_DIST" \
      || fail "StudyBreakGames build failed. Check StudyBreakGames/ for errors."
  else
    warn "npm/bun not found — cannot build StudyBreakGames."
    warn "Install Node.js (https://nodejs.org) and re-run install.sh to enable /games."
  fi
fi

# =============================================================================
# STEP 3 — Load config (.env / credentials.json)
# =============================================================================
step "Step 3 — Load configuration"

if [ -f "$SCRIPT_DIR/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    val="${val#\"}" ; val="${val%\"}" ; val="${val#\'}" ; val="${val%\'}"
    [ -z "${!key+x}" ] && export "$key"="$val"
  done < "$SCRIPT_DIR/.env"
  ok "Loaded .env"
fi

# Fall back to credentials.json
if [ -z "${INFERENCE_API_KEY:-}" ] && [ -f "$CREDS_PATH" ]; then
  INFERENCE_API_KEY=$(python3 -c "
import json
print(json.load(open('$CREDS_PATH')).get('INFERENCE_API_KEY',''))
" 2>/dev/null || true)
  [ -n "${INFERENCE_API_KEY:-}" ] && ok "INFERENCE_API_KEY from $CREDS_PATH"
fi

[ -z "${INFERENCE_API_KEY:-}" ]  && fail "INFERENCE_API_KEY not set. Add it to $SCRIPT_DIR/.env"
[ -z "${INFERENCE_MODEL:-}" ]    && fail "INFERENCE_MODEL not set. Add it to $SCRIPT_DIR/.env"
[ -z "${INFERENCE_BASE_URL:-}" ] && fail "INFERENCE_BASE_URL not set. Add it to $SCRIPT_DIR/.env"

INFERENCE_PROVIDER_TYPE="${INFERENCE_PROVIDER_TYPE:-nvidia}"
INFERENCE_PROVIDER_NAME="${INFERENCE_PROVIDER_NAME:-nvidia}"

ok "Provider     : $INFERENCE_PROVIDER_NAME ($INFERENCE_PROVIDER_TYPE)"
ok "Base URL     : $INFERENCE_BASE_URL"
ok "Model        : $INFERENCE_MODEL"

# Persist to credentials.json
mkdir -p "$(dirname "$CREDS_PATH")"
python3 -c "
import json, os
path = '$CREDS_PATH'
try: d = json.load(open(path))
except: d = {}
d.update({'INFERENCE_API_KEY':'$INFERENCE_API_KEY','INFERENCE_PROVIDER_TYPE':'$INFERENCE_PROVIDER_TYPE',
          'INFERENCE_PROVIDER_NAME':'$INFERENCE_PROVIDER_NAME','INFERENCE_BASE_URL':'$INFERENCE_BASE_URL',
          'INFERENCE_MODEL':'$INFERENCE_MODEL'})
open(path,'w').write(json.dumps(d, indent=2))
os.chmod(path, 0o600)
" 2>/dev/null || true

# =============================================================================
# STEP 4 — Onboard sandbox (only if none exists)
# =============================================================================
step "Step 4 — Sandbox"

_live_sandboxes() {
  openshell sandbox list 2>/dev/null \
    | sed 's/\x1b\[[0-9;]*m//g' \
    | grep -v "^No sandboxes" | grep -v "^NAME" \
    | awk '{print $1}' | grep -v '^$' || true
}

LIVE_COUNT=$(_live_sandboxes | wc -l | tr -d ' ')

if [ "${LIVE_COUNT:-0}" -eq 0 ]; then
  info "No sandbox found — running 'nemoclaw onboard' (non-interactive)..."
  # Drive nemoclaw onboard end-to-end without prompts.  The "NVIDIA Endpoints"
  # menu option points at integrate.api.nvidia.com (the API Catalog) and would
  # try to auth our INFERENCE_API_KEY against the wrong endpoint, so we pick
  # the "custom" (Other OpenAI-compatible) provider and feed it the Inference
  # Hub base URL + key directly.  Step 5 below replaces this provisional
  # provider with the canonical INFERENCE_PROVIDER_NAME anyway.
  export NEMOCLAW_NON_INTERACTIVE=1
  export NEMOCLAW_PROVIDER=custom
  export NEMOCLAW_ENDPOINT_URL="${INFERENCE_BASE_URL}"
  export NEMOCLAW_MODEL="${INFERENCE_MODEL}"
  export COMPATIBLE_API_KEY="${INFERENCE_API_KEY}"
  # Some legacy code paths still look for NVIDIA_API_KEY by name; stage the
  # same key there too so any incidental check finds a value.
  export NVIDIA_API_KEY="${INFERENCE_API_KEY}"
  nemoclaw onboard --non-interactive
  ok "Onboarding complete"

  info "Waiting for sandbox to become ready..."
  for i in $(seq 1 20); do
    LIVE_COUNT=$(_live_sandboxes | wc -l | tr -d ' ')
    [ "${LIVE_COUNT:-0}" -gt 0 ] && break
    sleep 2
  done
  [ "${LIVE_COUNT:-0}" -eq 0 ] && fail "No sandbox appeared after onboarding."
else
  ok "Sandbox(es) already exist — skipping onboarding"
fi

# ── Resolve sandbox name ──────────────────────────────────────────────────────
if [ -n "${SANDBOX_ARG:-}" ]; then
  SANDBOX_NAME="$SANDBOX_ARG"
else
  LIVE_NAMES=$(_live_sandboxes)
  LIVE_COUNT=$(echo "$LIVE_NAMES" | grep -c . || true)

  if [ "${LIVE_COUNT:-0}" -eq 1 ]; then
    SANDBOX_NAME=$(echo "$LIVE_NAMES" | head -1)
  else
    JSON_DEFAULT=$(python3 -c "
import json
try:
    d = json.load(open('$HOME/.nemoclaw/sandboxes.json'))
    print(d.get('defaultSandbox') or '')
except: pass
" 2>/dev/null || true)

    if [ -n "${JSON_DEFAULT:-}" ] && echo "$LIVE_NAMES" | grep -qx "$JSON_DEFAULT"; then
      SANDBOX_NAME="$JSON_DEFAULT"
    else
      echo ""
      echo -e "  ${YELLOW}Multiple sandboxes found:${NC}"
      echo "$LIVE_NAMES" | while read -r n; do echo "    - $n"; done
      echo -n "  Which sandbox to use? "
      read -r SANDBOX_NAME
    fi
  fi
fi

[ -z "${SANDBOX_NAME:-}" ] && fail "Could not determine sandbox. Re-run: bash install.sh <sandbox-name>"
_live_sandboxes | grep -qx "$SANDBOX_NAME" || fail "Sandbox '$SANDBOX_NAME' not found."
ok "Target sandbox: $SANDBOX_NAME"

# =============================================================================
# STEP 5 — Inference provider + model
# =============================================================================
step "Step 5 — Inference provider + model"

if openshell provider get "$INFERENCE_PROVIDER_NAME" >/dev/null 2>&1; then
  openshell provider update "$INFERENCE_PROVIDER_NAME" \
    --credential INFERENCE_API_KEY \
    --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL" \
    2>/dev/null \
    && ok "Provider '$INFERENCE_PROVIDER_NAME' updated" \
    || warn "Provider '$INFERENCE_PROVIDER_NAME' update failed — continuing"
else
  openshell provider create \
    --type  "$INFERENCE_PROVIDER_TYPE" \
    --name  "$INFERENCE_PROVIDER_NAME" \
    --credential INFERENCE_API_KEY \
    --config "NVIDIA_BASE_URL=$INFERENCE_BASE_URL" \
    && ok "Provider '$INFERENCE_PROVIDER_NAME' created" \
    || fail "Could not create inference provider."
fi

openshell inference set \
  --provider "$INFERENCE_PROVIDER_NAME" \
  --model    "$INFERENCE_MODEL" \
  && ok "Inference: $INFERENCE_PROVIDER_NAME / $INFERENCE_MODEL" \
  || fail "Could not set inference model."

# =============================================================================
# STEP 5c — Patch openclaw.json inside sandbox with correct model
# =============================================================================
step "Step 5c — Patch openclaw model inside sandbox"

# openclaw.json is root-owned (444) inside the sandbox — cannot be written by the
# sandbox user. We reach it via kubectl exec (root) through the cluster container.

# Detect the cluster container name (gateway name determines the container prefix)
_CLUSTER_CONTAINER=$(docker ps --format "{{.Names}}" 2>/dev/null \
  | grep "^openshell-cluster-" | head -1 || true)

if [ -z "${_CLUSTER_CONTAINER:-}" ]; then
  warn "OpenShell cluster container not found — skipping openclaw model patch."
  warn "Connect to the sandbox and run: openclaw onboard (choose $INFERENCE_MODEL)"
else
  docker exec "$_CLUSTER_CONTAINER" \
    kubectl exec -n openshell "$SANDBOX_NAME" -c agent -- \
    sh -c "
      python3 -c \"
import json, sys
with open('/sandbox/.openclaw/openclaw.json') as f:
    d = json.load(f)
model = '$INFERENCE_MODEL'
d['models']['providers']['inference']['models'] = [{
    'id': model,
    'name': 'inference/' + model,
    'reasoning': False,
    'input': ['text'],
    'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
    'contextWindow': 131072,
    'maxTokens': 4096
}]
d['agents']['defaults']['model']['primary'] = 'inference/' + model
with open('/sandbox/.openclaw/openclaw.json', 'w') as f:
    json.dump(d, f, indent=2)
\"
    " \
    && ok "openclaw patched: inference/$INFERENCE_MODEL" \
    || fail "Failed to patch openclaw.json inside sandbox."
fi

# =============================================================================
# STEP 6 — Host Python venv + MCP server
# =============================================================================
step "Step 5b — Detect host external address"

# Try to find the machine's LAN / public IP for the upload portal URL.
# Users need to reach port 8000 in their browser to upload PDFs.
if [ -z "${TA_EXTERNAL_URL:-}" ]; then
  _EXT_IP=$(hostname -I 2>/dev/null | awk '{print $1}' | tr -d '[:space:]' || true)
  # Fallback: try curl to a metadata endpoint or public IP service
  if [ -z "${_EXT_IP:-}" ]; then
    _EXT_IP=$(curl -sf --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null \
              || curl -sf --max-time 3 https://api4.my-ip.io/ip 2>/dev/null \
              || echo "")
  fi
  TA_EXTERNAL_URL="http://${_EXT_IP:-localhost}:8000"
fi
export TA_EXTERNAL_URL
ok "Upload portal : $TA_EXTERNAL_URL/upload"
warn "If users are on a different network, replace with the host's public IP/hostname."
warn "Override before running: export TA_EXTERNAL_URL=http://<your-host>:8000"

step "Step 6 — Host Python venv (fastmcp + httpx)"

cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  info "Creating host venv..."
  uv venv --python 3.10 --quiet
  ok "venv created at $SCRIPT_DIR/.venv"
else
  ok "Host venv already exists — skipping creation"
fi

info "Installing/verifying fastmcp + httpx..."
uv pip install --quiet fastmcp httpx
ok "fastmcp + httpx installed"

# Verify imports
.venv/bin/python3 -c "import fastmcp, httpx" \
  || fail "fastmcp/httpx import failed in host venv — check $SCRIPT_DIR/.venv"
ok "Import check passed"

step "Step 7 — MCP server (port $MCP_PORT)"

# Check if it's already running and healthy
if curl -s --max-time 2 "http://127.0.0.1:${MCP_PORT}/mcp" >/dev/null 2>&1; then
  ok "MCP server already running on port $MCP_PORT — skipping start"
else
  info "Starting MCP server in background..."
  (
    cd "$SCRIPT_DIR"
    source .venv/bin/activate
    export TA_EXTERNAL_URL="${TA_EXTERNAL_URL:-http://localhost:8000}"
    while true; do
      python3 ai_teaching_assistant_mcp_server.py --port "$MCP_PORT" \
        --ta-host "http://localhost:8000"
      echo "[ta-mcp] Server exited (code $?), restarting in 2s..." >> "$MCP_LOG_FILE"
      sleep 2
    done
  ) >> "$MCP_LOG_FILE" 2>&1 &

  echo $! > "$MCP_PID_FILE"
  ok "MCP server launched (PID $(cat $MCP_PID_FILE))"

  info "Waiting for MCP server to become ready..."
  MCP_UP=false
  for i in $(seq 1 15); do
    sleep 1
    if curl -s --max-time 2 "http://127.0.0.1:${MCP_PORT}/mcp" >/dev/null 2>&1; then
      MCP_UP=true; break
    fi
  done

  if $MCP_UP; then
    ok "MCP server is up on http://127.0.0.1:${MCP_PORT}/mcp"
  else
    kill -0 "$(cat $MCP_PID_FILE 2>/dev/null)" 2>/dev/null \
      && warn "MCP server started but not yet responding — check: tail -f $MCP_LOG_FILE" \
      || fail "MCP server process exited immediately. Check: cat $MCP_LOG_FILE"
  fi
fi

# =============================================================================
# STEP 8 — Sandbox network policy
# =============================================================================
step "Step 8 — Sandbox network policy"

POLICY_FILE="$SCRIPT_DIR/policy/sandbox_policy.yaml"
[ -f "$POLICY_FILE" ] || fail "Policy file not found: $POLICY_FILE"

openshell policy set "$SANDBOX_NAME" \
  --policy "$POLICY_FILE" \
  --wait \
  && ok "Policy applied (port $MCP_PORT allowed for skill venv)" \
  || fail "Failed to apply sandbox policy."

# =============================================================================
# STEP 9 — Upload skill to sandbox
# =============================================================================
step "Step 9 — Upload skill to sandbox"

SKILL_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SANDBOX_SKILL_ROOT}/SKILL.md && echo exists" 2>/dev/null || true)

if [ "$SKILL_CHECK" = "exists" ]; then
  ok "Skill already present in sandbox — re-uploading to apply any updates"
fi

openshell sandbox upload "$SANDBOX_NAME" \
  "$SKILL_SRC" \
  "$SANDBOX_SKILL_ROOT" \
  && ok "Skill uploaded to $SANDBOX_SKILL_ROOT" \
  || fail "Skill upload failed."

# Confirm upload
SKILL_CONFIRM=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SANDBOX_SKILL_ROOT}/SKILL.md && echo ok" 2>/dev/null || true)
[ "$SKILL_CONFIRM" = "ok" ] \
  || fail "SKILL.md not found in sandbox after upload — check upload path."
ok "Upload confirmed"

# ── Upload HEARTBEAT.md to sandbox workspace ──────────────────────────────────
# The agent reads this at session start — it injects TA skill routing rules
# so the agent always calls the right CLI tool instead of hallucinating.
HEARTBEAT_SRC="$SCRIPT_DIR/ai_teaching_assistant_skills/HEARTBEAT.md"
HEARTBEAT_DEST="/sandbox/.openclaw-data/workspace/HEARTBEAT.md"

if [ -f "$HEARTBEAT_SRC" ]; then
  openshell sandbox upload "$SANDBOX_NAME" \
    "$HEARTBEAT_SRC" \
    "$HEARTBEAT_DEST" \
    && ok "HEARTBEAT.md uploaded to sandbox workspace" \
    || warn "HEARTBEAT.md upload failed — agent may not invoke skill tools correctly"
fi

# =============================================================================
# STEP 10 — Write config.json into sandbox skill root
# =============================================================================
step "Step 10 — Write config.json"

# Prompt for user_id (can be skipped with USER_ID env var)
if [ -z "${TA_USER_ID:-}" ]; then
  echo ""
  echo -n "  Enter the default user_id for the skill config (e.g. testuser): "
  read -r TA_USER_ID
fi
[ -z "${TA_USER_ID:-}" ] && warn "No user_id provided — config.json will not have a default user_id"

CONFIG_JSON="{\"user_id\":\"${TA_USER_ID:-}\",\"server_url\":\"http://host.openshell.internal:${MCP_PORT}/mcp\"}"

openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "echo '${CONFIG_JSON}' > ${SANDBOX_SKILL_ROOT}/config.json" \
  && ok "config.json written to $SANDBOX_SKILL_ROOT/config.json" \
  || warn "Could not write config.json — run setup_config.py inside the sandbox manually"

# =============================================================================
# STEP 11 — Bootstrap skill venv inside sandbox
# =============================================================================
step "Step 11 — Skill venv (sandbox)"

SKILL_VENV="${SANDBOX_SKILL_ROOT}/venv"

# Check if venv + fastmcp already present
VENV_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SKILL_VENV}/bin/python3 && ${SKILL_VENV}/bin/python3 -c 'import fastmcp; print(fastmcp.__version__)' 2>/dev/null || echo missing" \
  2>/dev/null || echo missing)

if [ "$VENV_CHECK" = "missing" ]; then
  info "Creating skill venv..."
  openshell sandbox exec -n "$SANDBOX_NAME" -- \
    python3 -m venv "$SKILL_VENV" \
    || fail "Failed to create skill venv inside sandbox."
  ok "Skill venv created"

  info "Installing fastmcp..."
  openshell sandbox exec -n "$SANDBOX_NAME" -- \
    "${SKILL_VENV}/bin/pip" install -q fastmcp \
    || fail "pip install fastmcp failed inside sandbox."
  ok "fastmcp installed"
else
  ok "fastmcp $VENV_CHECK already installed in skill venv — skipping"
fi

# Final import check
IMPORT_CHECK=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "${SKILL_VENV}/bin/python3" -c "import fastmcp; print('ok')" 2>/dev/null || true)
[ "$IMPORT_CHECK" = "ok" ] \
  || fail "fastmcp import check failed in skill venv. Re-run install.sh."
ok "fastmcp import verified in skill venv"

# =============================================================================
# STEP 11b — Upload sandbox markdown files to OpenClaw workspace
# =============================================================================
step "Step 11b — Upload sandbox markdown files"

SANDBOX_MD_SRC="$SCRIPT_DIR/sandbox_markdown_files"
SANDBOX_MD_DEST="/sandbox/.openclaw/workspace"

if [ ! -d "$SANDBOX_MD_SRC" ]; then
  warn "sandbox_markdown_files/ not found at $SANDBOX_MD_SRC — skipping"
else
  _md_ok=0
  _md_fail=0
  for _md_file in "$SANDBOX_MD_SRC"/*.md; do
    [ -f "$_md_file" ] || continue
    _md_name=$(basename "$_md_file")
    openshell sandbox upload "$SANDBOX_NAME" \
      "$_md_file" \
      "${SANDBOX_MD_DEST}/${_md_name}" \
      && { ok "$_md_name → $SANDBOX_MD_DEST/"; _md_ok=$((_md_ok + 1)); } \
      || { warn "$_md_name upload failed"; _md_fail=$((_md_fail + 1)); }
  done
  if [ "$_md_ok" -gt 0 ]; then
    ok "$_md_ok markdown file(s) uploaded to $SANDBOX_MD_DEST"
  fi
  [ "$_md_fail" -gt 0 ] && warn "$_md_fail markdown file(s) failed to upload"
fi

# =============================================================================
# STEP 12 — Final verification
# =============================================================================
step "Step 12 — Verification"

_check() {
  local label="$1" result="$2"
  [ "$result" = "ok" ] \
    && ok "$label" \
    || warn "$label — FAILED (check logs)"
}

# TA API
TA_STATUS=$(curl -sf --max-time 3 "http://localhost:8000/" >/dev/null 2>&1 && echo ok || echo fail)
_check "TA API       : http://localhost:8000"  "$TA_STATUS"

# MCP server
MCP_STATUS=$(curl -s --max-time 3 "http://127.0.0.1:${MCP_PORT}/mcp" 2>&1 | wc -c || echo 0)
[ "${MCP_STATUS:-0}" -gt 0 ] \
  && ok "MCP server   : http://127.0.0.1:${MCP_PORT}/mcp" \
  || warn "MCP server   : not responding — check: cat $MCP_LOG_FILE"

# Skill in sandbox
SKILL_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SANDBOX_SKILL_ROOT}/SKILL.md && echo ok" 2>/dev/null || true)
_check "Skill upload : $SANDBOX_SKILL_ROOT"  "$SKILL_V"

# config.json
CFG_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f ${SANDBOX_SKILL_ROOT}/config.json && echo ok" 2>/dev/null || true)
_check "config.json  : $SANDBOX_SKILL_ROOT"  "$CFG_V"

# Sandbox markdown files
MD_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  sh -c "test -f /sandbox/.openclaw/workspace/HEARTBEAT.md && echo ok" 2>/dev/null || true)
_check "Sandbox MDs  : /sandbox/.openclaw/workspace/"  "$MD_V"

# fastmcp in skill venv
FM_V=$(openshell sandbox exec -n "$SANDBOX_NAME" -- \
  "${SKILL_VENV}/bin/python3" -c "import fastmcp; print('ok')" 2>/dev/null || true)
_check "fastmcp venv : $SKILL_VENV"  "$FM_V"

# Study Break Games SPA
GAMES_V=$([ -f "$SCRIPT_DIR/StudyBreakGames/dist/index.html" ] && echo ok || echo fail)
_check "Games SPA    : StudyBreakGames/dist/"  "$GAMES_V"

# RAG services: ingestor + RAG server
INGESTOR_V=$(curl -sf --max-time 3 "http://localhost:8082/v1/health" >/dev/null 2>&1 && echo ok || echo fail)
_check "Ingestor     : http://localhost:8082"  "$INGESTOR_V"
RAG_V=$(curl -sf --max-time 3 "http://localhost:8081/v1/health" >/dev/null 2>&1 && echo ok || echo fail)
_check "RAG server   : http://localhost:8081"  "$RAG_V"

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Installation complete!                                  ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  TA API       : http://localhost:8000/docs"
echo "  Upload portal: ${TA_EXTERNAL_URL:-http://localhost:8000}/upload"
echo "  Games portal : ${TA_EXTERNAL_URL:-http://localhost:8000}/games/"
echo "  MCP server   : http://127.0.0.1:${MCP_PORT}/mcp  (PID $(cat $MCP_PID_FILE 2>/dev/null || echo '?'))"
echo "  Sandbox URL  : http://host.openshell.internal:${MCP_PORT}/mcp"
echo "  MCP logs     : tail -f $MCP_LOG_FILE"
echo "  TA logs      : make logs-api  |  make logs-gradio"
echo ""
echo "  PDF Upload (for users on a different network):"
echo "    ssh -L 8000:<this-host-ip>:8000 user@<this-host>"
echo "    → open http://localhost:8000/upload in their browser"
echo ""
echo "  Next steps:"
echo "    1. Connect : nemoclaw $SANDBOX_NAME connect"
echo "    2. Try: \"I want to upload my PDF\""
echo "    3. Try: \"Generate a curriculum for me\""
echo "    4. Try: \"List my subtopics\""
echo "    5. Try: \"Give me a quiz on subtopic 0\""
echo "    6. Try: \"What are the key concepts in this chapter?\""
echo ""
echo "  Update config.json (user_id / server_url):"
echo "    openshell sandbox exec -n $SANDBOX_NAME -- \\"
echo "      ${SKILL_VENV}/bin/python3 ${SANDBOX_SKILL_ROOT}/scripts/setup_config.py"
echo ""
echo "  Restart MCP server:"
echo "    kill \$(cat $MCP_PID_FILE) && bash $SCRIPT_DIR/install.sh $SANDBOX_NAME"
echo ""