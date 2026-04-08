#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Host-side OAuth2 access token server for gogcli.
#
# Holds the refresh token on the host and serves fresh access tokens to the
# NemoClaw sandbox. The sandbox never sees the refresh token — only short-lived
# access tokens (~1 hour). A gog wrapper inside the sandbox calls this server
# on each invocation, so tokens are always fresh.
#
# Usage:
#   GOG_KEYRING_BACKEND=file GOG_KEYRING_PASSWORD=<pw> \
#     python3 scripts/gog-token-server.py <email> [--port 9100] [--gog /path/to/gog]
#
# Endpoints:
#   GET /token   — returns a valid access token (plain text)
#   GET /health  — returns "ok"

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Token cache ────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_access_token: str = ""
_expires_at: float = 0.0


def _exchange(client_id: str, client_secret: str, refresh_token: str) -> tuple[str, float]:
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        result = json.loads(resp.read())
    token = result["access_token"]
    expires_in = int(result.get("expires_in", 3600))
    return token, time.monotonic() + expires_in


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Return a valid access token, refreshing if within 5 minutes of expiry."""
    global _access_token, _expires_at
    with _lock:
        if _access_token and time.monotonic() < _expires_at - 300:
            return _access_token
        log.info("Refreshing access token...")
        _access_token, _expires_at = _exchange(client_id, client_secret, refresh_token)
        log.info("Token refreshed, valid for ~%ds", int(_expires_at - time.monotonic()))
        return _access_token


# ── HTTP handler ───────────────────────────────────────────────────────────────

def make_handler(client_id: str, client_secret: str, refresh_token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self._respond(200, "ok")
            elif self.path == "/token":
                try:
                    token = get_access_token(client_id, client_secret, refresh_token)
                    self._respond(200, token)
                except Exception as exc:
                    log.error("Token refresh failed: %s", exc)
                    self._respond(500, f"error: {exc}")
            else:
                self._respond(404, "not found")

        def _respond(self, status: int, body: str) -> None:
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, fmt, *args) -> None:  # noqa: ANN001
            log.debug("HTTP %s", fmt % args)

    return Handler


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _export_refresh_token(gog_bin: str, email: str) -> str:
    """Export the stored refresh token for `email` via `gog auth tokens export`."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        subprocess.run(
            [gog_bin, "auth", "tokens", "export", email, "--out", tmp_path, "--overwrite"],
            check=True,
            capture_output=True,
        )
        with open(tmp_path) as f:
            data = json.load(f)
        refresh_token = data.get("refresh_token", "")
        if not refresh_token:
            sys.exit(f"Error: refresh_token missing from export file for {email}")
        return refresh_token
    except subprocess.CalledProcessError as exc:
        sys.exit(f"Error exporting refresh token: {exc.stderr.decode().strip()}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _load_credentials(config_dir: str) -> tuple[str, str]:
    creds_path = os.path.join(config_dir, "credentials.json")
    try:
        with open(creds_path) as f:
            data = json.load(f)
        return data["client_id"], data["client_secret"]
    except (FileNotFoundError, KeyError) as exc:
        sys.exit(f"Error reading {creds_path}: {exc}")


def _find_gog(hint: str, repo_dir: str) -> str:
    if hint and os.path.isfile(hint) and os.access(hint, os.X_OK):
        return hint
    for candidate in [
        os.path.expanduser("~/demo/gogcli/bin/gog"),
        os.path.expanduser("~/gogcli/bin/gog"),
        os.path.join(os.path.dirname(repo_dir), "gogcli", "bin", "gog"),
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    import shutil
    found = shutil.which("gog")
    if found:
        return found
    sys.exit("Error: gog binary not found. Build it first or pass --gog /path/to/gog")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="gogcli host-side OAuth2 token server")
    parser.add_argument("email", help="Gmail account address")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GOG_TOKEN_SERVER_PORT", "9100")),
        help="Port to listen on (default: 9100, env: GOG_TOKEN_SERVER_PORT)",
    )
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--gog", default="", help="Path to gog binary (auto-detected if omitted)")
    args = parser.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gog_bin = _find_gog(args.gog, repo_dir)
    log.info("Using gog binary: %s", gog_bin)

    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_dir = os.path.join(xdg, "gogcli")

    client_id, client_secret = _load_credentials(config_dir)

    log.info("Exporting refresh token for %s...", args.email)
    refresh_token = _export_refresh_token(gog_bin, args.email)

    # Verify credentials before accepting connections
    log.info("Verifying with initial token exchange...")
    try:
        get_access_token(client_id, client_secret, refresh_token)
    except Exception as exc:
        sys.exit(f"Error: initial token exchange failed: {exc}")

    server = HTTPServer((args.bind, args.port), make_handler(client_id, client_secret, refresh_token))
    log.info("Token server ready on %s:%d", args.bind, args.port)
    log.info("Sandbox wrapper calls: curl -sf http://<host-ip>:%d/token", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
