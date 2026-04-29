#!/usr/bin/env python3
"""Host-side OAuth2 token push daemon for NemoClaw Google integration.

Reads Google OAuth2 credentials from ~/.nemoclaw/credentials.json,
exchanges the refresh token for short-lived access tokens, and pushes
them into the sandbox via `openshell sandbox upload`.  No network port
is exposed -- the sandbox reads the token from a file.

Usage:
    python3 gog-push-daemon.py <sandbox-name> [--openshell /path/to/openshell]
"""

import argparse
import json
import logging
import os
import re
import shutil
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

CREDS_PATH = os.path.expanduser("~/.nemoclaw/credentials.json")
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
PID_FILE = os.path.expanduser("~/.nemoclaw/gog-push-daemon.pid")
SANDBOX_TOKEN_DIR = "/sandbox/.openclaw-data/gogcli"


def write_pid():
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def remove_pid():
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


def load_creds():
    with open(CREDS_PATH) as f:
        d = json.load(f)
    cid = d.get("GOOGLE_CLIENT_ID", "")
    cs = d.get("GOOGLE_CLIENT_SECRET", "")
    rt = d.get("GOOGLE_REFRESH_TOKEN", "")
    if not all([cid, cs, rt]):
        raise KeyError("Missing GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, or GOOGLE_REFRESH_TOKEN")
    return cid, cs, rt


def exchange(client_id, client_secret, refresh_token):
    """Exchange refresh token for short-lived access token."""
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        TOKEN_ENDPOINT, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    token = result["access_token"]
    expires_in = int(result.get("expires_in", 3600))
    return token, time.time() + expires_in


def get_sandbox_id(name, openshell_bin):
    """Return sandbox UUID to detect sandbox replacements."""
    try:
        r = subprocess.run(
            [openshell_bin, "sandbox", "get", name],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"openshell sandbox get failed: {e.stderr.strip()}") from e
    clean = re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", r.stdout)
    m = re.search(r"Id:\s+([0-9a-f-]{36})", clean)
    if not m:
        raise RuntimeError("Sandbox UUID not found in openshell output")
    return m.group(1)


def push_token(name, token, expiry_ts, openshell_bin):
    """Write token + expiry to temp dir and upload into sandbox."""
    tmp = tempfile.mkdtemp(prefix="gog-token-")
    try:
        with open(os.path.join(tmp, "access_token"), "w") as f:
            f.write(token)
        with open(os.path.join(tmp, "token_expiry"), "w") as f:
            f.write(str(int(expiry_ts)))
        subprocess.run(
            [openshell_bin, "sandbox", "upload", name, tmp, SANDBOX_TOKEN_DIR],
            check=True, capture_output=True, text=True,
        )
        log.info("Token pushed to sandbox '%s', expires %s", name, time.ctime(expiry_ts))
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"openshell sandbox upload failed: {e.stderr.strip()}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Google OAuth2 token push daemon")
    parser.add_argument("sandbox", help="OpenShell sandbox name")
    parser.add_argument("--openshell", default="openshell", help="Path to openshell binary")
    args = parser.parse_args()

    cid, cs, rt = load_creds()
    log.info("Credentials loaded from %s", CREDS_PATH)

    log.info("Resolving sandbox '%s'...", args.sandbox)
    expected_id = get_sandbox_id(args.sandbox, args.openshell)
    log.info("Sandbox ID: %s", expected_id)

    log.info("Initial token exchange...")
    token, expiry = exchange(cid, cs, rt)

    log.info("Pushing initial token...")
    push_token(args.sandbox, token, expiry, args.openshell)

    write_pid()
    log.info("Push daemon ready (pid %d)", os.getpid())

    def shutdown(signum, _):
        log.info("Signal %d, shutting down.", signum)
        remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    backoff = [5, 15, 30, 60, 120]

    try:
        while True:
            sleep_secs = max(0.0, expiry - time.time() - 600)
            log.info("Next refresh in %.0fs", sleep_secs)
            time.sleep(sleep_secs)

            for attempt in range(5):
                try:
                    cur_id = get_sandbox_id(args.sandbox, args.openshell)
                    if cur_id != expected_id:
                        log.info("Sandbox replaced (%s -> %s), exiting.", expected_id, cur_id)
                        remove_pid()
                        sys.exit(0)

                    cid, cs, rt = load_creds()
                    token, expiry = exchange(cid, cs, rt)
                    push_token(args.sandbox, token, expiry, args.openshell)
                    break
                except Exception as e:
                    log.warning("Attempt %d/5 failed: %s", attempt + 1, e)
                    if attempt < 4:
                        time.sleep(backoff[attempt])
                    else:
                        log.error("Max retries, exiting.")
                        remove_pid()
                        sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        remove_pid()
        raise


if __name__ == "__main__":
    main()
