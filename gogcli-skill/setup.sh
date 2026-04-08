#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Set up gogcli (Google Workspace CLI) inside a NemoClaw sandbox.
#
# The refresh token stays on the host inside a token server (gog-token-server.py).
# The sandbox gets a thin gog wrapper that fetches a fresh access token from the
# host on every invocation — no credentials are stored inside the sandbox.
#
# Prerequisites:
#   1. gog binary built (run `make` in gogcli repo, or pass path explicitly)
#   2. bootstrap.sh already run on the host (sets up credentials + keyring)
#   3. GOG_KEYRING_PASSWORD exported (same value used during bootstrap)
#
# Usage:
#   GOG_KEYRING_PASSWORD=<pw> ./gogcli-skill/setup.sh [sandbox-name] [gog-binary]
#
#   sandbox-name  — OpenShell sandbox name (default: email)
#   gog-binary    — path to built gog binary (default: searches PATH + common locations)
#
# Optional env:
#   GOG_ACCOUNT           — Gmail address for the token server (default: first account in keyring)
#   GOG_TOKEN_SERVER_PORT — token server port (default: 9100)

set -euo pipefail

SANDBOX=${1:-email}
GOG_BIN_OVERRIDE=${2:-}
TOKEN_PORT="${GOG_TOKEN_SERVER_PORT:-9100}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Locate the gog binary ─────────────────────────────────────────────────────

resolve_gog_binary() {
  if [[ -n "$GOG_BIN_OVERRIDE" ]]; then
    echo "$GOG_BIN_OVERRIDE"
    return
  fi
  for candidate in \
    "$(command -v gog 2>/dev/null || true)" \
    "$HOME/demo/gogcli/bin/gog" \
    "$HOME/gogcli/bin/gog" \
    "$(dirname "$(dirname "$SKILL_DIR")")/gogcli/bin/gog"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return
    fi
  done
  echo ""
}

GOG_BIN="$(resolve_gog_binary)"

if [[ -z "$GOG_BIN" ]]; then
  echo "Error: gog binary not found."
  echo ""
  echo "Build it first:"
  echo "  cd ~/demo/gogcli && make"
  echo ""
  echo "Or pass the path explicitly:"
  echo "  $0 $SANDBOX /path/to/bin/gog"
  exit 1
fi

echo "Using gog binary: $GOG_BIN"

# ── Validate gogcli credentials on the host ───────────────────────────────────

GOG_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gogcli"

if [[ ! -d "$GOG_CONFIG_DIR" ]]; then
  echo "Error: gogcli config not found at $GOG_CONFIG_DIR"
  echo ""
  echo "Run bootstrap first:"
  echo "  GOG_KEYRING_PASSWORD=<pw> ./gogcli-skill/bootstrap.sh you@gmail.com"
  exit 1
fi

if [[ -z "${GOG_KEYRING_PASSWORD:-}" ]]; then
  echo "Error: GOG_KEYRING_PASSWORD is required."
  echo ""
  echo "  export GOG_KEYRING_PASSWORD=<your-keyring-password>"
  echo "  $0 $SANDBOX"
  exit 1
fi

# ── Resolve host account ──────────────────────────────────────────────────────

GOG_ACCOUNT="${GOG_ACCOUNT:-}"
if [[ -z "$GOG_ACCOUNT" ]]; then
  GOG_ACCOUNT=$(XDG_CONFIG_HOME="${GOG_CONFIG_DIR%/gogcli}" GOG_KEYRING_BACKEND=file \
    GOG_KEYRING_PASSWORD="$GOG_KEYRING_PASSWORD" \
    "$GOG_BIN" auth list --plain 2>/dev/null | awk 'NR==1{print $1}')
fi
if [[ -z "$GOG_ACCOUNT" ]]; then
  echo "Error: could not detect account from keyring. Set GOG_ACCOUNT env var:"
  echo "  export GOG_ACCOUNT=you@gmail.com"
  exit 1
fi

# ── Determine host IP ─────────────────────────────────────────────────────────

HOST_IP="$(hostname -I | awk '{print $1}')"
if [[ -z "$HOST_IP" ]]; then
  echo "Error: could not determine host IP address."
  exit 1
fi
echo "Host IP: $HOST_IP"

# ── Start (or restart) the token server ──────────────────────────────────────
#
# The token server holds the refresh token on the host and serves fresh access
# tokens to the sandbox on demand. The sandbox never sees the refresh token.

TOKEN_SERVER_PID_FILE="$HOME/.config/gogcli/token-server.pid"

start_token_server() {
  if [[ -f "$TOKEN_SERVER_PID_FILE" ]]; then
    OLD_PID=$(cat "$TOKEN_SERVER_PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
      echo "Stopping existing token server (pid $OLD_PID)..."
      kill "$OLD_PID" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$TOKEN_SERVER_PID_FILE"
  fi

  echo "Starting token server on port $TOKEN_PORT..."
  GOG_KEYRING_BACKEND=file \
  GOG_KEYRING_PASSWORD="$GOG_KEYRING_PASSWORD" \
  XDG_CONFIG_HOME="${GOG_CONFIG_DIR%/gogcli}" \
  nohup python3 "$SKILL_DIR/gog-token-server.py" \
    "$GOG_ACCOUNT" \
    --port "$TOKEN_PORT" \
    --gog "$GOG_BIN" \
    > "$HOME/.config/gogcli/token-server.log" 2>&1 &
  echo $! > "$TOKEN_SERVER_PID_FILE"

  local retries=10
  while (( retries-- > 0 )); do
    if curl -sf "http://127.0.0.1:${TOKEN_PORT}/health" >/dev/null 2>&1; then
      echo "Token server ready (pid $(cat "$TOKEN_SERVER_PID_FILE"))."
      return 0
    fi
    sleep 1
  done
  echo "Warning: token server did not respond within 10s; check $HOME/.config/gogcli/token-server.log"
}

start_token_server

# ── Build sandbox upload directory ───────────────────────────────────────────
#
# Upload the gog config (credentials.json, config.json) plus a gog wrapper
# script that fetches a fresh access token from the host on each call.
# The keyring directory is intentionally excluded — credentials stay on the host.

UPLOAD_DIR=$(mktemp -d /tmp/gogcli-upload-XXXXXX)
trap 'rm -rf "$UPLOAD_DIR"' EXIT

cp -r "$GOG_CONFIG_DIR/." "$UPLOAD_DIR/"
rm -rf "$UPLOAD_DIR/keyring" "$UPLOAD_DIR/gog" "$UPLOAD_DIR/gog-bin" "$UPLOAD_DIR/env.sh" \
       "$UPLOAD_DIR/token-server.pid" "$UPLOAD_DIR/token-server.log"

cp "$GOG_BIN" "$UPLOAD_DIR/gog-bin"
chmod +x "$UPLOAD_DIR/gog-bin"

cat > "$UPLOAD_DIR/gog" <<WRAPEOF
#!/bin/bash
# gogcli wrapper — fetches a fresh access token from the host token server.
# Re-run setup.sh to update host IP or port.
_GOG_TOKEN="\$(curl -sf 'http://${HOST_IP}:${TOKEN_PORT}/token')" || {
  echo "gogcli: could not reach token server at ${HOST_IP}:${TOKEN_PORT}" >&2
  exit 1
}
export XDG_CONFIG_HOME=/sandbox/.config
exec env GOG_ACCESS_TOKEN="\$_GOG_TOKEN" /sandbox/.config/gogcli/gog-bin "\$@"
WRAPEOF
chmod +x "$UPLOAD_DIR/gog"

echo "Uploading gogcli config + wrapper..."
openshell sandbox upload "$SANDBOX" "$UPLOAD_DIR" /sandbox/.config/gogcli

# ── Apply gogcli network policy ───────────────────────────────────────────────

echo "Applying gogcli network policy..."

CURRENT=$(openshell policy get --full "$SANDBOX" 2>/dev/null | awk '/^---/{found=1; next} found{print}')

GOOGLE_BLOCKS=$(awk '
  /^  google_gmail:/ || /^  google_calendar:/ || /^  google_drive:/ { found=1 }
  /^  [a-z]/ && found && !/^  google_gmail:/ && !/^  google_calendar:/ && !/^  google_drive:/ { found=0 }
  found { print }
' "$SKILL_DIR/policy.yaml")

TOKEN_SERVER_BLOCK=$(cat <<TSEOF
  google_token_server:
    name: google_token_server
    endpoints:
      - host: ${HOST_IP}
        port: ${TOKEN_PORT}
        protocol: rest
        enforcement: enforce
        tls: passthrough
        rules:
          - allow: { method: GET, path: "/token" }
          - allow: { method: GET, path: "/health" }
    binaries:
      - { path: /usr/bin/curl }
      - { path: /usr/bin/curl* }
TSEOF
)

POLICY_FILE=$(mktemp /tmp/gogcli-policy-XXXXXX.yaml)
echo "${CURRENT:-version: 1}" > "$POLICY_FILE"
if ! grep -q "^network_policies:" "$POLICY_FILE"; then
  echo "" >> "$POLICY_FILE"
  echo "network_policies:" >> "$POLICY_FILE"
fi
printf '%s\n' "$GOOGLE_BLOCKS" >> "$POLICY_FILE"
printf '%s\n' "$TOKEN_SERVER_BLOCK" >> "$POLICY_FILE"
openshell policy set --policy "$POLICY_FILE" --wait "$SANDBOX"
rm -f "$POLICY_FILE"

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "Done. Token server running on ${HOST_IP}:${TOKEN_PORT} (pid $(cat "$TOKEN_SERVER_PID_FILE" 2>/dev/null || echo '?'))."
echo "  Log: $HOME/.config/gogcli/token-server.log"
echo ""
echo "To verify inside the sandbox:"
echo "  openshell sandbox connect $SANDBOX"
echo "  /sandbox/.config/gogcli/gog auth list"
echo ""
echo "Demo prompts:"
echo "  \"Search my Gmail for unread messages from NVIDIA and summarize them.\""
echo "  \"Check my calendar for meetings tomorrow and give me a prep briefing.\""
echo "  \"List recent files in my Google Drive shared with my team.\""
