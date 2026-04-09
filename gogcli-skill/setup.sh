#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Set up gogcli (Google Workspace CLI) inside a NemoClaw sandbox.
#
# The refresh token stays on the host inside the push daemon (gog-token-server.py).
# The daemon exchanges the refresh token for short-lived access tokens and pushes
# them directly into the sandbox filesystem — no network socket is exposed.
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
#   GOG_ACCOUNT           — Gmail address for the push daemon (default: first account in keyring)

set -euo pipefail

SANDBOX=${1:-email}
GOG_BIN_OVERRIDE=${2:-}
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -- Locate the gog binary -----------------------------------------------------

resolve_gog_binary() {
  if [[ -n "$GOG_BIN_OVERRIDE" ]]; then
    echo "$GOG_BIN_OVERRIDE"
    return
  fi
  for candidate in \
    "$(command -v gog 2>/dev/null || true)" \
    "$(dirname "$(dirname "$SKILL_DIR")")/gogcli/bin/gog" \
    "$HOME/gogcli/bin/gog"; do
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
  echo "Build it first (or re-run bootstrap.sh which builds automatically):"
  echo "  cd <gogcli-repo> && make"
  echo ""
  echo "Or pass the path explicitly:"
  echo "  $0 $SANDBOX /path/to/bin/gog"
  exit 1
fi

echo "Using gog binary: $GOG_BIN"

# -- Validate gogcli credentials on the host -----------------------------------

GOG_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gogcli"

if [[ ! -d "$GOG_CONFIG_DIR" ]]; then
  echo "Error: gogcli config not found at $GOG_CONFIG_DIR"
  echo ""
  echo "Run bootstrap first:"
  echo "  GOG_KEYRING_PASSWORD=<pw> ./gogcli-skill/bootstrap.sh --credentials <file> --email <addr> --sandbox <name>"
  exit 1
fi

if [[ -z "${GOG_KEYRING_PASSWORD:-}" ]]; then
  echo "Error: GOG_KEYRING_PASSWORD is required."
  echo ""
  echo "  export GOG_KEYRING_PASSWORD=<your-keyring-password>"
  echo "  $0 $SANDBOX"
  exit 1
fi

# -- Resolve host account ------------------------------------------------------

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

# -- Start (or restart) the push daemon ----------------------------------------
#
# The push daemon holds the refresh token on the host, exchanges it for
# short-lived access tokens, and pushes them into the sandbox filesystem via
# `openshell sandbox upload`. No network socket is exposed.

PUSH_DAEMON_PID_FILE="$HOME/.config/gogcli/push-daemon.pid"
if [[ -f "$PUSH_DAEMON_PID_FILE" ]]; then
  OLD_PID=$(cat "$PUSH_DAEMON_PID_FILE" 2>/dev/null || true)
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping existing push daemon (pid $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PUSH_DAEMON_PID_FILE"
fi

echo "Starting push daemon..."
GOG_KEYRING_BACKEND=file \
GOG_KEYRING_PASSWORD="$GOG_KEYRING_PASSWORD" \
XDG_CONFIG_HOME="${GOG_CONFIG_DIR%/gogcli}" \
nohup python3 "$SKILL_DIR/gog-token-server.py" \
  "$GOG_ACCOUNT" \
  "$SANDBOX" \
  --gog "$GOG_BIN" \
  > "$HOME/.config/gogcli/push-daemon.log" 2>&1 &

# Wait for first token push (check for token file in sandbox)
echo "Waiting for initial token push..."
retries=15
while (( retries-- > 0 )); do
  if grep -q "Token pushed to sandbox" "$HOME/.config/gogcli/push-daemon.log" 2>/dev/null; then
    echo "Token pushed successfully."
    break
  fi
  sleep 1
done

# -- Build sandbox upload directory -------------------------------------------
#
# Upload the gog config (credentials.json, config.json) plus a gog wrapper
# script that reads the access token from the file pushed by the daemon.
# The keyring directory is intentionally excluded — credentials stay on the host.

UPLOAD_DIR=$(mktemp -d /tmp/gogcli-upload-XXXXXX)
trap 'rm -rf "$UPLOAD_DIR"' EXIT

cp -r "$GOG_CONFIG_DIR/." "$UPLOAD_DIR/"
rm -rf "$UPLOAD_DIR/keyring" "$UPLOAD_DIR/gog" "$UPLOAD_DIR/gog-bin" "$UPLOAD_DIR/env.sh" \
       "$UPLOAD_DIR/push-daemon.pid" "$UPLOAD_DIR/push-daemon.log"

echo "Uploading gogcli config..."
openshell sandbox upload "$SANDBOX" "$UPLOAD_DIR" /sandbox/.config/gogcli

# Install gog-bin (actual binary) + gog (wrapper) to /sandbox/.config/gogcli/bin/ —
# a subdirectory registered as read-only in filesystem_policy. The wrapper reads the
# token from /sandbox/.openclaw-data/gogcli/access_token (writable).

GOG_BIN_UPLOAD=$(mktemp -d /tmp/gogcli-bin-XXXXXX)
trap 'rm -rf "$UPLOAD_DIR" "$GOG_BIN_UPLOAD"' EXIT

cp "$GOG_BIN" "$GOG_BIN_UPLOAD/gog-bin"
chmod +x "$GOG_BIN_UPLOAD/gog-bin"

cat > "$GOG_BIN_UPLOAD/gog" <<'WRAPEOF'
#!/bin/bash
# gogcli wrapper — reads access token pushed by host push daemon.
_GOG_TOKEN="$(cat /sandbox/.openclaw-data/gogcli/access_token 2>/dev/null)" || {
  echo "gogcli: token not found. Is the push daemon running? Re-run setup.sh." >&2
  exit 1
}
if [ -f /sandbox/.openclaw-data/gogcli/token_expiry ]; then
  _EXPIRY=$(cat /sandbox/.openclaw-data/gogcli/token_expiry)
  _NOW=$(date +%s)
  if [ "$_NOW" -gt "$_EXPIRY" ]; then
    echo "gogcli: token expired. Push daemon will refresh shortly, or re-run setup.sh." >&2
    exit 1
  fi
fi
export XDG_CONFIG_HOME=/sandbox/.config
exec env GOG_ACCESS_TOKEN="$_GOG_TOKEN" /sandbox/.config/gogcli/bin/gog-bin "$@"
WRAPEOF
chmod +x "$GOG_BIN_UPLOAD/gog"

echo "Installing gog-bin and gog wrapper to /sandbox/.config/gogcli/bin/..."
openshell sandbox upload "$SANDBOX" "$GOG_BIN_UPLOAD" /sandbox/.config/gogcli/bin

# -- Add gog to PATH via .bashrc -----------------------------------------------

echo "Adding /sandbox/.config/gogcli/bin to sandbox PATH..."
openshell sandbox exec -n "$SANDBOX" -- bash -c \
  'grep -q "gogcli/bin" /sandbox/.bashrc || echo "export PATH=\"/sandbox/.config/gogcli/bin:\$PATH\"" >> /sandbox/.bashrc'

# -- Apply gogcli network policy and filesystem read-only entry ----------------
#
# gog-bin lives at /sandbox/.config/gogcli/bin/gog-bin. The parent /sandbox is
# read_write, so we register the bin/ subdirectory as a more-specific read_only
# entry. OpenShell's proxy trusts binaries whose containing directory is in the
# read_only list. Token files in the parent /sandbox/.config/gogcli/ remain writable.

echo "Applying gogcli network policy..."

CURRENT=$(openshell policy get --full "$SANDBOX" 2>/dev/null | awk '/^---/{found=1; next} found{print}')

GOOGLE_BLOCKS=$(awk '
  /^  google_gmail:/ || /^  google_calendar:/ || /^  google_drive:/ { found=1 }
  /^  [a-z]/ && found && !/^  google_gmail:/ && !/^  google_calendar:/ && !/^  google_drive:/ { found=0 }
  found { print }
' "$SKILL_DIR/policy.yaml")

POLICY_FILE=$(mktemp /tmp/gogcli-policy-XXXXXX.yaml)

# Start with current policy (or a minimal skeleton)
echo "${CURRENT:-version: 1}" > "$POLICY_FILE"

# Ensure filesystem_policy.read_only includes /sandbox/.config/gogcli/bin
if ! grep -q "/sandbox/.config/gogcli/bin" "$POLICY_FILE"; then
  # Insert after the last read_only entry (before read_write: section)
  sed -i '/^  read_only:/,/^  read_write:/{/^  read_write:/i\  - /sandbox/.config/gogcli/bin
}' "$POLICY_FILE" 2>/dev/null || true
  # Fallback: if sed-insert didn't work, append the entry directly after read_only block
  if ! grep -q "/sandbox/.config/gogcli/bin" "$POLICY_FILE"; then
    sed -i 's|^  read_write:|  - /sandbox/.config/gogcli/bin\n  read_write:|' "$POLICY_FILE"
  fi
fi

if ! grep -q "^network_policies:" "$POLICY_FILE"; then
  echo "" >> "$POLICY_FILE"
  echo "network_policies:" >> "$POLICY_FILE"
fi
printf '%s\n' "$GOOGLE_BLOCKS" >> "$POLICY_FILE"
openshell policy set --policy "$POLICY_FILE" --wait "$SANDBOX"
rm -f "$POLICY_FILE"

# -- Done ----------------------------------------------------------------------

echo ""
echo "Done. Push daemon running (log: $HOME/.config/gogcli/push-daemon.log)."
echo "  GOG_ACCESS_TOKEN is refreshed live via openclaw config set — no network socket exposed."
echo ""
echo "Demo prompts:"
echo "  \"Search my Gmail for unread messages from NVIDIA and summarize them.\""
echo "  \"Check my calendar for meetings tomorrow and give me a prep briefing.\""
echo "  \"List recent files in my Google Drive shared with my team.\""
