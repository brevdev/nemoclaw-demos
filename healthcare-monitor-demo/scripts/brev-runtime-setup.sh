#!/usr/bin/env bash
set -euo pipefail

SANDBOX="${NEMOCLAW_SANDBOX:-healthcare-monitor}"
DEFAULT_MODEL="nvidia/nemotron-3-super-120b-a12b"
DEFAULT_ENDPOINT_URL="https://integrate.api.nvidia.com/v1/chat/completions"
MODEL="${NEMOCLAW_MODEL:-$DEFAULT_MODEL}"
PROVIDER="${NEMOCLAW_PROVIDER:-build}"
ENDPOINT_URL="${NEMOCLAW_ENDPOINT_URL:-$DEFAULT_ENDPOINT_URL}"
POLICY_TIER="${NEMOCLAW_POLICY_TIER:-restricted}"
POLICY_MODE="${NEMOCLAW_POLICY_MODE:-suggested}"
INSTALL_IF_MISSING="${NEMOCLAW_INSTALL_IF_MISSING:-0}"
DESTROY_EXISTING="${NEMOCLAW_DESTROY_EXISTING:-0}"
APPLY_LOCAL_POLICY="${NEMOCLAW_APPLY_LOCAL_POLICY:-1}"
ACCEPT_THIRD_PARTY_SOFTWARE="${NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE:-1}"
ALLOW_PROVIDER_OVERRIDE="${NEMOCLAW_ALLOW_PROVIDER_OVERRIDE:-0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKERFILE="$ROOT/Dockerfile.sandbox"

echo "Healthcare Monitor Demo runtime setup for sandbox: $SANDBOX"

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp

  touch "$ROOT/.env"
  chmod 600 "$ROOT/.env"

  tmp="$(mktemp)"
  if grep -q "^${key}=" "$ROOT/.env"; then
    awk -v key="$key" -v value="$value" '
      index($0, key "=") == 1 { print key "=" value; next }
      { print }
    ' "$ROOT/.env" > "$tmp"
  else
    cp "$ROOT/.env" "$tmp"
    printf '\n%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  cat "$tmp" > "$ROOT/.env"
  rm -f "$tmp"
}

if [[ ! -f "$ROOT/.env" && -f "$ROOT/.env.example" ]]; then
  install -m 600 "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env from .env.example."
fi

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$ROOT/.env"
  set +a
  SANDBOX="${NEMOCLAW_SANDBOX:-$SANDBOX}"
  MODEL="${NEMOCLAW_MODEL:-$MODEL}"
  PROVIDER="${NEMOCLAW_PROVIDER:-$PROVIDER}"
  ENDPOINT_URL="${NEMOCLAW_ENDPOINT_URL:-$ENDPOINT_URL}"
  POLICY_TIER="${NEMOCLAW_POLICY_TIER:-$POLICY_TIER}"
  POLICY_MODE="${NEMOCLAW_POLICY_MODE:-$POLICY_MODE}"
  INSTALL_IF_MISSING="${NEMOCLAW_INSTALL_IF_MISSING:-$INSTALL_IF_MISSING}"
  DESTROY_EXISTING="${NEMOCLAW_FORCE_DESTROY_EXISTING:-${NEMOCLAW_DESTROY_EXISTING:-$DESTROY_EXISTING}}"
  APPLY_LOCAL_POLICY="${NEMOCLAW_APPLY_LOCAL_POLICY:-$APPLY_LOCAL_POLICY}"
  ACCEPT_THIRD_PARTY_SOFTWARE="${NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE:-$ACCEPT_THIRD_PARTY_SOFTWARE}"
  ALLOW_PROVIDER_OVERRIDE="${NEMOCLAW_ALLOW_PROVIDER_OVERRIDE:-$ALLOW_PROVIDER_OVERRIDE}"
fi

if [[ "$ALLOW_PROVIDER_OVERRIDE" != "1" && "$PROVIDER" != "build" ]]; then
  PROVIDER="build"
  export NEMOCLAW_PROVIDER="$PROVIDER"
  set_env_value "NEMOCLAW_PROVIDER" "$PROVIDER"
  echo "Updated provider in .env to NemoClaw build provider."
fi

if [[ "$ALLOW_PROVIDER_OVERRIDE" != "1" && "$MODEL" != "$DEFAULT_MODEL" ]]; then
  MODEL="$DEFAULT_MODEL"
  export NEMOCLAW_MODEL="$MODEL"
  set_env_value "NEMOCLAW_MODEL" "$MODEL"
  echo "Updated model in .env for the release target: $MODEL"
fi

if [[ "$ALLOW_PROVIDER_OVERRIDE" != "1" && "$ENDPOINT_URL" != "$DEFAULT_ENDPOINT_URL" ]]; then
  ENDPOINT_URL="$DEFAULT_ENDPOINT_URL"
  export NEMOCLAW_ENDPOINT_URL="$ENDPOINT_URL"
  set_env_value "NEMOCLAW_ENDPOINT_URL" "$ENDPOINT_URL"
  echo "Updated endpoint in .env for the release target: $ENDPOINT_URL"
fi

if [[ "$ALLOW_PROVIDER_OVERRIDE" == "1" && "$PROVIDER" != "build" && "$PROVIDER" != "custom" && "$ENDPOINT_URL" == "$DEFAULT_ENDPOINT_URL" ]]; then
  ENDPOINT_URL=""
  export NEMOCLAW_ENDPOINT_URL=""
  echo "Using provider-managed endpoint for provider override: $PROVIDER"
fi

required_credential_name() {
  case "$PROVIDER" in
    build)
      echo "NVIDIA_API_KEY"
      ;;
    openai)
      echo "OPENAI_API_KEY"
      ;;
    anthropic)
      echo "ANTHROPIC_API_KEY"
      ;;
    anthropicCompatible)
      echo "COMPATIBLE_ANTHROPIC_API_KEY"
      ;;
    gemini)
      echo "GEMINI_API_KEY"
      ;;
    custom)
      echo "NEMOCLAW_PROVIDER_KEY"
      ;;
    *)
      echo "NEMOCLAW_PROVIDER_KEY"
      ;;
  esac
}

CREDENTIAL_NAME="$(required_credential_name)"
CREDENTIAL_VALUE="${!CREDENTIAL_NAME:-}"
if [[ "$PROVIDER" == "build" && -z "$CREDENTIAL_VALUE" && -n "${NEMOCLAW_PROVIDER_KEY:-}" ]]; then
  CREDENTIAL_VALUE="$NEMOCLAW_PROVIDER_KEY"
  export NVIDIA_API_KEY="$NEMOCLAW_PROVIDER_KEY"
  set_env_value "NVIDIA_API_KEY" "$NEMOCLAW_PROVIDER_KEY"
  echo "Copied NEMOCLAW_PROVIDER_KEY into NVIDIA_API_KEY for the build provider."
fi
if [[ "$PROVIDER" == "custom" && -z "$CREDENTIAL_VALUE" && -n "${COMPATIBLE_API_KEY:-}" ]]; then
  CREDENTIAL_VALUE="$COMPATIBLE_API_KEY"
  export NEMOCLAW_PROVIDER_KEY="$COMPATIBLE_API_KEY"
fi

if [[ -z "$CREDENTIAL_VALUE" ]]; then
  if [[ -t 0 ]]; then
    read -rsp "Enter $CREDENTIAL_NAME for NemoClaw onboarding: " CREDENTIAL_VALUE
    echo
    if [[ -z "$CREDENTIAL_VALUE" ]]; then
      echo "$CREDENTIAL_NAME is required for non-interactive onboarding." >&2
      exit 1
    fi
    export "$CREDENTIAL_NAME=$CREDENTIAL_VALUE"
    if [[ "$PROVIDER" == "custom" ]]; then
      export NEMOCLAW_PROVIDER_KEY="$CREDENTIAL_VALUE"
      set_env_value "NEMOCLAW_PROVIDER_KEY" "$CREDENTIAL_VALUE"
    else
      set_env_value "$CREDENTIAL_NAME" "$CREDENTIAL_VALUE"
    fi
    echo "Saved $CREDENTIAL_NAME to .env."
  else
    echo "$CREDENTIAL_NAME is not set and this shell is not interactive. Add it to .env first." >&2
    exit 1
  fi
fi

if ! command -v nemoclaw >/dev/null 2>&1 || ! command -v openshell >/dev/null 2>&1; then
  if [[ "$INSTALL_IF_MISSING" == "1" ]]; then
    echo "NemoClaw/OpenShell missing; running installer because NEMOCLAW_INSTALL_IF_MISSING=1."
    NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE="$ACCEPT_THIRD_PARTY_SOFTWARE" \
      bash -c 'curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash'
    # shellcheck disable=SC1090
    [[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc" || true
  else
    echo "Missing nemoclaw or openshell on this host." >&2
    echo "Install NemoClaw first, or set NEMOCLAW_INSTALL_IF_MISSING=1 if you accept the installer behavior." >&2
    exit 1
  fi
fi

for command in nemoclaw openshell python3 docker; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

if [[ ! -f "$DOCKERFILE" ]]; then
  echo "Missing custom sandbox Dockerfile: $DOCKERFILE" >&2
  exit 1
fi

echo "Provider:   $PROVIDER"
echo "Endpoint:   ${ENDPOINT_URL:-provider default}"
echo "Model:      $MODEL"
echo "Policy:     $POLICY_TIER/$POLICY_MODE"
echo "Dockerfile: $DOCKERFILE"

if [[ "$PROVIDER" == "build" ]]; then
  "$SCRIPT_DIR/patch-nemoclaw-build-provider.sh"
else
  echo "Skipping build-provider compatibility patch for provider: $PROVIDER"
fi
"$SCRIPT_DIR/run-local-verification.sh"

if [[ "$DESTROY_EXISTING" == "1" ]]; then
  echo "Destroying existing sandbox because NEMOCLAW_DESTROY_EXISTING=1: $SANDBOX"
  nemoclaw "$SANDBOX" destroy --yes || true
else
  echo "Not destroying existing sandbox. Set NEMOCLAW_DESTROY_EXISTING=1 only for intentional rebuilds."
fi

# Remove any installer-default sandbox (e.g. my-assistant) that was auto-created
# during NEMOCLAW_INSTALL_IF_MISSING=1. That sandbox occupies port 18789, which
# causes the project sandbox to fall back to port 18790. OpenClaw CLI defaults to
# 18789, so it cannot connect to the gateway and hangs in embedded-mode retries.
# This cleanup runs unconditionally so re-runs on existing installs are also safe.
if command -v openshell >/dev/null 2>&1; then
  while IFS= read -r sandbox_name; do
    if [[ -n "$sandbox_name" && "$sandbox_name" != "NAME" && "$sandbox_name" != "$SANDBOX" ]]; then
      echo "Removing installer-default sandbox '$sandbox_name' to free port 18789 for $SANDBOX."
      nemoclaw "$sandbox_name" destroy --yes 2>/dev/null || true
    fi
  done < <(openshell sandbox list 2>/dev/null | awk 'NR>1 {print $1}')
fi

NEMOCLAW_NON_INTERACTIVE=1 \
NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE="$ACCEPT_THIRD_PARTY_SOFTWARE" \
NEMOCLAW_PROVIDER="$PROVIDER" \
NEMOCLAW_MODEL="$MODEL" \
NEMOCLAW_ENDPOINT_URL="$ENDPOINT_URL" \
NEMOCLAW_POLICY_TIER="$POLICY_TIER" \
NEMOCLAW_POLICY_MODE="$POLICY_MODE" \
NEMOCLAW_SANDBOX_NAME="$SANDBOX" \
nemoclaw onboard --non-interactive --from "$DOCKERFILE" --yes-i-accept-third-party-software

if [[ "$APPLY_LOCAL_POLICY" == "1" ]]; then
  "$SCRIPT_DIR/apply-demo-policy.sh"
else
  echo "Skipping local policy because NEMOCLAW_APPLY_LOCAL_POLICY=0."
fi

# Warm up the persistent OpenClaw gateway inside the sandbox.
# The gateway is NOT started automatically at sandbox boot — it starts on the
# first 'nemoclaw connect' call. Without this step, every 'openclaw agent'
# command falls back to embedded mode. Embedded mode uses an ephemeral
# inline gateway, so sessions_spawn cannot find the parent session and
# sub-agents silently fail to coordinate. The persistent gateway must be
# running before any multi-agent workflow is attempted.
echo "Warming up OpenClaw gateway in sandbox: $SANDBOX"
nemoclaw "$SANDBOX" connect --probe-only

echo "Runtime setup finished."
echo "  nemoclaw '$SANDBOX' status"
echo "  ./scripts/start-demo-app.sh"
echo "  ./scripts/open-openshell-tui.sh"
