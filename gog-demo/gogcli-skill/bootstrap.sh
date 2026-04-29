#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Bootstrap gogcli end-to-end: credentials → keyring → token server → sandbox.
#
# Usage:
#   GOG_KEYRING_PASSWORD=<pw> ./gogcli-skill/bootstrap.sh \
#     --credentials <file> \
#     --email <gmail-address> \
#     --sandbox <sandbox-name>
#
# Required:
#   --credentials   Path to a GCP Console OAuth client secret JSON file
#                   (the file downloaded from console.cloud.google.com).
#                   Passed directly to `gog auth credentials set`.
#   --email         Gmail address to authorise.
#   --sandbox       OpenShell sandbox name to push gogcli into.
#
# Optional:
#   --gog           Path to a pre-built gog binary (skips clone/build).
#   --gogcli-repo   Path to an existing gogcli checkout (default: auto-detected
#                   as a sibling dir; cloned from GitHub if not found).
#   (no --port option — token delivery uses push daemon, no network port needed)
#
# The script automatically installs Go and clones/builds gogcli if needed.
#
# Environment:
#   GOG_KEYRING_PASSWORD   Encrypts the local token file. Required.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -- Parse flags ---------------------------------------------------------------

CREDS_FILE=""
EMAIL=""
SANDBOX=""
GOG_BIN_OVERRIDE=""
GOGCLI_REPO_OVERRIDE=""

usage() {
  echo "Usage: GOG_KEYRING_PASSWORD=<pw> $0 \\"
  echo "         --credentials <file> --email <addr> --sandbox <name>"
  echo ""
  echo "  --credentials  GCP Console OAuth client secret JSON"
  echo "  --email        Gmail address"
  echo "  --sandbox      OpenShell sandbox name"
  echo "  --gog          Path to a pre-built gog binary (skips clone/build)"
  echo "  --gogcli-repo  Path to an existing gogcli checkout (auto-detected/cloned if omitted)"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --credentials) CREDS_FILE="$2"; shift 2 ;;
    --email)       EMAIL="$2";      shift 2 ;;
    --sandbox)     SANDBOX="$2";    shift 2 ;;
    --gogcli-repo) GOGCLI_REPO_OVERRIDE="$2"; shift 2 ;;
    --gog)         GOG_BIN_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

[[ -z "$CREDS_FILE" ]]  && echo "Error: --credentials is required." && usage
[[ -z "$EMAIL" ]]       && echo "Error: --email is required."       && usage
[[ -z "$SANDBOX" ]]     && echo "Error: --sandbox is required."     && usage

if [[ ! -f "$CREDS_FILE" ]]; then
  echo "Error: credentials file not found: $CREDS_FILE"
  exit 1
fi

if [[ -z "${GOG_KEYRING_PASSWORD:-}" ]]; then
  echo "Error: GOG_KEYRING_PASSWORD is required."
  echo "  export GOG_KEYRING_PASSWORD=<choose-any-password>"
  exit 1
fi

# -- Pre-flight checks --------------------------------------------------------

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)  ;;
  Darwin) ;;
  *)
    echo "Error: unsupported OS '$OS'. Only Linux and macOS are supported."
    exit 1
    ;;
esac

for cmd in git python3 curl make; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: required command '$cmd' not found."
    exit 1
  fi
done

GO_MIN_MAJOR=1
GO_MIN_MINOR=21
GO_INSTALL_VERSION="1.23.8"

go_version_ok() {
  local ver
  ver="$(go version 2>/dev/null | sed -E 's/.*go([0-9]+\.[0-9]+).*/\1/')" || return 1
  local major="${ver%%.*}" minor="${ver#*.}"
  (( major > GO_MIN_MAJOR || (major == GO_MIN_MAJOR && minor >= GO_MIN_MINOR) ))
}

install_go() {
  local go_os go_arch
  case "$OS" in
    Linux)  go_os="linux"  ;;
    Darwin) go_os="darwin" ;;
  esac
  case "$ARCH" in
    x86_64)  go_arch="amd64" ;;
    aarch64) go_arch="arm64" ;;
    arm64)   go_arch="arm64" ;;
    *)
      echo "Error: unsupported architecture '$ARCH' for Go install."
      exit 1
      ;;
  esac

  local tarball="go${GO_INSTALL_VERSION}.${go_os}-${go_arch}.tar.gz"
  local url="https://go.dev/dl/${tarball}"
  local install_dir="$HOME/.local/go"

  echo "Installing Go ${GO_INSTALL_VERSION} to ${install_dir} ..."
  mkdir -p "$HOME/.local"
  rm -rf "$install_dir"
  curl -fsSL "$url" | tar -C "$HOME/.local" -xz

  export PATH="$install_dir/bin:$PATH"

  if ! go version &>/dev/null; then
    echo "Error: Go installation failed."
    exit 1
  fi
  echo "Installed $(go version)"
}

if [[ -z "$GOG_BIN_OVERRIDE" ]]; then
  if ! command -v go &>/dev/null; then
    echo "Go toolchain not found — installing automatically..."
    install_go
  elif ! go_version_ok; then
    echo "Go $(go version | sed -E 's/.*go([0-9]+\.[0-9]+[^ ]*).*/\1/') is too old (need ${GO_MIN_MAJOR}.${GO_MIN_MINOR}+) — upgrading..."
    install_go
  fi
fi

echo "OS: $OS ($ARCH)"

# -- Locate (and optionally build) the gog binary -----------------------------

GOGCLI_REPO_URL="https://github.com/steipete/gogcli.git"
GOGCLI_REPO="${GOGCLI_REPO_OVERRIDE:-$(dirname "$(dirname "$SKILL_DIR")")/gogcli}"

if [[ -n "$GOG_BIN_OVERRIDE" ]]; then
  GOG_BIN="$GOG_BIN_OVERRIDE"
elif GOG_BIN="$(command -v gog 2>/dev/null)" && [[ -x "$GOG_BIN" ]]; then
  : # found on PATH
elif GOG_BIN="$GOGCLI_REPO/bin/gog" && [[ -x "$GOG_BIN" ]]; then
  : # already built in repo
else
  if [[ ! -d "$GOGCLI_REPO" ]]; then
    echo "Cloning gogcli to $GOGCLI_REPO ..."
    if ! GIT_TERMINAL_PROMPT=0 git clone "$GOGCLI_REPO_URL" "$GOGCLI_REPO" 2>&1; then
      rm -rf "$GOGCLI_REPO"
      echo ""
      echo "Error: failed to clone $GOGCLI_REPO_URL"
      echo "If the repo is private, clone it manually first:"
      echo "  git clone $GOGCLI_REPO_URL $GOGCLI_REPO"
      exit 1
    fi
  fi

  echo "Building gog from $GOGCLI_REPO ..."
  make -C "$GOGCLI_REPO"
fi

if [[ ! -x "$GOG_BIN" ]]; then
  echo "Error: failed to obtain a working gog binary."
  echo ""
  echo "Pass a pre-built binary to skip the automatic build:"
  echo "  $0 --gog /path/to/bin/gog ..."
  exit 1
fi

echo "Using gog binary: $GOG_BIN"
echo "Account: $EMAIL"

GOG_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gogcli"

GOG_ENV=(
  env
  XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
  GOG_KEYRING_BACKEND=file
  GOG_KEYRING_PASSWORD="$GOG_KEYRING_PASSWORD"
)

# -- Store OAuth client credentials --------------------------------------------

echo "Storing OAuth client credentials..."
"${GOG_ENV[@]}" "$GOG_BIN" auth credentials set "$CREDS_FILE"

# -- Authorise account (OAuth consent flow) ------------------------------------

echo ""
echo "Authorising $EMAIL — a browser window will open. Sign in and grant access."
echo ""
"${GOG_ENV[@]}" "$GOG_BIN" auth add "$EMAIL" \
  --services gmail,calendar,drive \
  --manual

# -- Verify keyring ------------------------------------------------------------

echo "Verifying keyring..."
"${GOG_ENV[@]}" "$GOG_BIN" auth list

# -- Start (or restart) push daemon -------------------------------------------
#
# The push daemon holds the refresh token on the host, exchanges it for
# short-lived access tokens, and pushes them into the sandbox filesystem via
# `openshell sandbox upload`. No network socket is exposed.

PUSH_DAEMON_PID_FILE="$GOG_CONFIG_DIR/push-daemon.pid"

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
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
nohup python3 "$SKILL_DIR/gog-token-server.py" \
  "$EMAIL" \
  "$SANDBOX" \
  --gog "$GOG_BIN" \
  > "$GOG_CONFIG_DIR/push-daemon.log" 2>&1 &
echo $! > "$PUSH_DAEMON_PID_FILE"

echo "Waiting for initial token push..."
retries=15
while (( retries-- > 0 )); do
  if grep -q "Token pushed to sandbox" "$GOG_CONFIG_DIR/push-daemon.log" 2>/dev/null; then
    echo "Token pushed successfully (pid $(cat "$PUSH_DAEMON_PID_FILE"))."
    break
  fi
  sleep 1
done
if (( retries < 0 )); then
  echo "Warning: push daemon did not deliver token within 15s; check $GOG_CONFIG_DIR/push-daemon.log"
fi

# -- Push gogcli into sandbox --------------------------------------------------

UPLOAD_DIR=$(mktemp -d /tmp/gogcli-upload-XXXXXX)
trap 'rm -rf "$UPLOAD_DIR"' EXIT

cp -r "$GOG_CONFIG_DIR/." "$UPLOAD_DIR/"
rm -rf "$UPLOAD_DIR/keyring" "$UPLOAD_DIR/gog" "$UPLOAD_DIR/gog-bin" "$UPLOAD_DIR/env.sh" \
       "$UPLOAD_DIR/push-daemon.pid" "$UPLOAD_DIR/push-daemon.log"

echo "Uploading gogcli config into sandbox '$SANDBOX'..."
openshell sandbox upload "$SANDBOX" "$UPLOAD_DIR" /sandbox/.config/gogcli

# Install gog-bin (actual binary) + gog (wrapper) to /sandbox/.config/gogcli/bin/ —
# a subdirectory registered as read-only in filesystem_policy. OpenShell's proxy
# trusts binaries whose parent directory is listed in filesystem_policy.read_only;
# /sandbox/.config/gogcli/bin satisfies that requirement. The wrapper reads the access
# token from /sandbox/.openclaw-data/gogcli/access_token (writable), which is updated
# by the push daemon without requiring any network socket.

GOG_BIN_UPLOAD=$(mktemp -d /tmp/gogcli-bin-XXXXXX)
trap 'rm -rf "$UPLOAD_DIR" "$GOG_BIN_UPLOAD"' EXIT

# Actual binary
cp "$GOG_BIN" "$GOG_BIN_UPLOAD/gog-bin"
chmod +x "$GOG_BIN_UPLOAD/gog-bin"

# Wrapper script — reads token from .openclaw-data (writable), execs real binary
cat > "$GOG_BIN_UPLOAD/gog" <<'WRAPEOF'
#!/bin/bash
# gogcli wrapper — reads access token pushed by host push daemon.
_GOG_TOKEN="$(cat /sandbox/.openclaw-data/gogcli/access_token 2>/dev/null)" || {
  echo "gogcli: token not found. Is the push daemon running? Re-run bootstrap.sh." >&2
  exit 1
}
if [ -f /sandbox/.openclaw-data/gogcli/token_expiry ]; then
  _EXPIRY=$(cat /sandbox/.openclaw-data/gogcli/token_expiry)
  _NOW=$(date +%s)
  if [ "$_NOW" -gt "$_EXPIRY" ]; then
    echo "gogcli: token expired. Push daemon will refresh shortly, or re-run bootstrap.sh." >&2
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

# -- Apply network policy and filesystem read-only entry -----------------------
#
# gog-bin lives at /sandbox/.config/gogcli/bin/gog-bin. The parent /sandbox is
# read_write, so we register the bin/ subdirectory as a more-specific read_only
# entry. OpenShell's proxy trusts binaries whose containing directory is in the
# read_only list. Token files in the parent /sandbox/.config/gogcli/ remain writable.

echo "Applying network policy..."

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
echo "gogcli ready in sandbox '$SANDBOX'."
echo "  Push daemon pid: $(cat "$PUSH_DAEMON_PID_FILE" 2>/dev/null || echo '?')"
echo "  Log: $GOG_CONFIG_DIR/push-daemon.log"
echo "  GOG_ACCESS_TOKEN is refreshed live via openclaw config set — no network socket exposed."
echo ""
echo "Try it:"
echo "  \"Search my Gmail for unread messages and summarize them.\""
echo "  \"Check my calendar for meetings tomorrow.\""
echo "  \"List recent files in my Google Drive.\""
