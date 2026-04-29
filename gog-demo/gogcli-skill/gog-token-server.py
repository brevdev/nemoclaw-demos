#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Host-side OAuth2 token push daemon for gogcli.
#
# Holds the refresh token on the host, exchanges it for short-lived access
# tokens, and pushes them into the NemoClaw sandbox via
# `openshell sandbox upload` to /sandbox/.openclaw-data/gogcli/ (writable).
# No network socket is exposed — the `gog` wrapper script reads the token
# directly from the file.
#
# Usage:
#   GOG_KEYRING_BACKEND=file GOG_KEYRING_PASSWORD=<pw> \
#     python3 gog-token-server.py <email> <sandbox> \
#       [--gog /path/to/gog] [--openshell /path/to/openshell]

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── PID file ───────────────────────────────────────────────────────────────────

PID_FILE = os.path.expanduser("~/.config/gogcli/push-daemon.pid")


def _write_pid_file() -> None:
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid_file() -> None:
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


# ── OAuth2 token exchange ──────────────────────────────────────────────────────

def exchange(client_id: str, client_secret: str, refresh_token: str) -> tuple[str, float]:
    """Exchange refresh token for access token. Returns (token, expiry_unix_timestamp)."""
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
    expiry_ts = time.time() + expires_in
    return token, expiry_ts


# ── Sandbox helpers ────────────────────────────────────────────────────────────

def get_sandbox_id(sandbox_name: str, openshell_bin: str) -> str:
    """Return the sandbox UUID by parsing `openshell sandbox get` output."""
    try:
        result = subprocess.run(
            [openshell_bin, "sandbox", "get", sandbox_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"openshell sandbox get failed: {exc.stderr.strip()}"
        ) from exc

    # Strip ANSI escape codes before parsing.
    clean = re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", result.stdout)
    match = re.search(r"Id:\s+([0-9a-f-]{36})", clean)
    if not match:
        raise RuntimeError(
            f"Sandbox UUID not found in 'openshell sandbox get {sandbox_name}' output"
        )
    return match.group(1)


def push_token_to_sandbox(
    sandbox_name: str,
    token: str,
    expiry_ts: float,
    openshell_bin: str,
) -> None:
    """Write token files to a temp dir and upload them to the writable sandbox data dir."""
    tmp_dir = tempfile.mkdtemp(prefix="gogcli-token-")
    try:
        with open(os.path.join(tmp_dir, "access_token"), "w") as f:
            f.write(token)
        with open(os.path.join(tmp_dir, "token_expiry"), "w") as f:
            f.write(str(int(expiry_ts)))

        subprocess.run(
            [openshell_bin, "sandbox", "upload", sandbox_name, tmp_dir,
             "/sandbox/.openclaw-data/gogcli"],
            check=True,
            capture_output=True,
            text=True,
        )
        log.info("Token pushed to sandbox '%s', expires at %s", sandbox_name, time.ctime(expiry_ts))
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"openshell sandbox upload failed: {exc.stderr.strip()}"
        ) from exc
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Bootstrap helpers ──────────────────────────────────────────────────────────

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


def _find_openshell(hint: str) -> str:
    if hint and os.path.isfile(hint) and os.access(hint, os.X_OK):
        return hint
    import shutil
    found = shutil.which("openshell")
    if found:
        return found
    sys.exit("Error: openshell binary not found. Install it or pass --openshell /path/to/openshell")


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="gogcli host-side OAuth2 token push daemon")
    parser.add_argument("email", help="Gmail account address")
    parser.add_argument("sandbox", help="OpenShell sandbox name")
    parser.add_argument("--gog", default="", help="Path to gog binary (auto-detected if omitted)")
    parser.add_argument(
        "--openshell",
        default="",
        help="Path to openshell binary (default: openshell on PATH)",
    )
    args = parser.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gog_bin = _find_gog(args.gog, repo_dir)
    openshell_bin = _find_openshell(args.openshell)
    log.info("Using gog binary: %s", gog_bin)
    log.info("Using openshell binary: %s", openshell_bin)

    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_dir = os.path.join(xdg, "gogcli")

    # ── Startup ────────────────────────────────────────────────────────────────

    client_id, client_secret = _load_credentials(config_dir)

    log.info("Exporting refresh token for %s...", args.email)
    refresh_token = _export_refresh_token(gog_bin, args.email)

    log.info("Resolving sandbox ID for '%s'...", args.sandbox)
    try:
        expected_sandbox_id = get_sandbox_id(args.sandbox, openshell_bin)
    except RuntimeError as exc:
        sys.exit(f"Error: {exc}")
    log.info("Sandbox ID: %s", expected_sandbox_id)

    log.info("Performing initial token exchange...")
    try:
        token, token_expiry = exchange(client_id, client_secret, refresh_token)
    except Exception as exc:
        sys.exit(f"Error: initial token exchange failed: {exc}")

    log.info("Pushing initial token to sandbox...")
    try:
        push_token_to_sandbox(args.sandbox, token, token_expiry, openshell_bin)
    except RuntimeError as exc:
        sys.exit(f"Error: initial token push failed: {exc}")

    _write_pid_file()
    log.info("Push daemon ready. PID file: %s", PID_FILE)

    # ── Signal handlers ────────────────────────────────────────────────────────

    def _shutdown(signum, frame):  # noqa: ANN001
        log.info("Received signal %d, shutting down.", signum)
        _remove_pid_file()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # ── Main loop ──────────────────────────────────────────────────────────────

    BACKOFF = [5, 15, 30, 60, 120]

    try:
        while True:
            # Sleep until 10 minutes before expiry
            sleep_secs = max(0.0, token_expiry - time.time() - 600)
            log.info("Next refresh in %.0fs (at %s)", sleep_secs, time.ctime(token_expiry - 600))
            time.sleep(sleep_secs)

            retries = 0
            while retries < 5:
                try:
                    # Verify the sandbox hasn't been replaced
                    current_id = get_sandbox_id(args.sandbox, openshell_bin)
                    if current_id != expected_sandbox_id:
                        log.info(
                            "Sandbox ID changed (%s → %s), sandbox was replaced. Exiting.",
                            expected_sandbox_id,
                            current_id,
                        )
                        _remove_pid_file()
                        sys.exit(0)

                    # Refresh token
                    new_token, new_expiry = exchange(client_id, client_secret, refresh_token)

                    # Push to sandbox
                    push_token_to_sandbox(args.sandbox, new_token, new_expiry, openshell_bin)

                    token_expiry = new_expiry
                    break

                except Exception as exc:
                    log.warning("Push failed (attempt %d/5): %s", retries + 1, exc)
                    retries += 1
                    if retries < 5:
                        time.sleep(BACKOFF[retries - 1])
                    else:
                        log.error("Max retries exceeded, sandbox unreachable. Exiting.")
                        _remove_pid_file()
                        sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        _remove_pid_file()
        raise


if __name__ == "__main__":
    main()
