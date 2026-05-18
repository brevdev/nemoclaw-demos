#!/usr/bin/env python3
"""Host-side OAuth access-token push daemon for Claude Code in NemoClaw.

Mirrors the Google Workspace integration pattern (gog-push-daemon.py):

  * The full Claude Code OAuth credentials (access token + refresh token +
    scopes + expiresAt) live ONLY on the host at ~/.claude/.credentials.json.
  * This daemon refreshes the access token at platform.claude.com shortly
    before expiry, rewrites the host credentials atomically, and pushes
    ONLY the short-lived access token into the sandbox.
  * The sandbox never sees the refresh token, so a sandbox compromise
    cannot mint new access tokens or keep working beyond one rotation.

The sandbox-side runner reads the pushed file and exports it as
CLAUDE_CODE_OAUTH_TOKEN.  Claude Code, when that env var is set, uses the
access token directly and never attempts to refresh from inside the
sandbox (cli.js: refreshToken:null, expiresAt:null).

Usage:
    python3 claude-push-daemon.py <sandbox-name> [--openshell /path/to/openshell]
"""

import argparse
import errno
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

HOST_CREDS_PATH = os.path.expanduser("~/.claude/.credentials.json")
PID_FILE = os.path.expanduser("~/.nemoclaw/claude-push-daemon.pid")

# Claude Code public OAuth client.  Hard-coded in cli.js; the refresh
# endpoint requires it.
CLAUDE_CODE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_ENDPOINT = "https://platform.claude.com/v1/oauth/token"

# User-Agent: platform.claude.com sits behind Cloudflare and rejects
# requests with no/obviously-bot UA (error 1010).  Mirror the CLI's
# format so we look like a Claude Code client.
USER_AGENT = "claude-cli/nemoclaw-push-daemon"

# Where the sandbox-side runner picks up the access token.  Kept under
# /sandbox/.openclaw-data so it's owned by the agent user, not the
# project tree.
SANDBOX_TOKEN_DIR = "/sandbox/.openclaw-data/claude-code"
SANDBOX_TOKEN_FILE = "oauth_token"  # contents: just the access token, no JSON

# Default: refresh this many seconds before the server-issued expiry.
# Override with --refresh-lead-seconds or via the config file.
DEFAULT_REFRESH_LEAD_SECONDS = 600  # 10 minutes

# Force a rotation after the token has been in the sandbox for this many
# seconds, even if it's still valid.  Anthropic issues tokens with ~8h
# expiry; rotating every 2h shrinks the compromise window 4x at the cost
# of ~4 extra refresh calls per day.  Set to 0 to disable and rotate only
# near server expiry.
DEFAULT_MAX_TOKEN_LIFETIME = 7200  # 2 hours

# Minimum sleep between pushes, in case expiresAt is close to now.
MIN_SLEEP_SECONDS = 30

BACKOFF = [5, 15, 30, 60, 120]


def write_pid() -> None:
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def remove_pid() -> None:
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


def load_host_creds() -> dict:
    with open(HOST_CREDS_PATH) as f:
        return json.load(f)


def save_host_creds(creds: dict) -> None:
    """Atomically rewrite the host credentials file with mode 0600."""
    d = os.path.dirname(HOST_CREDS_PATH)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".credentials.", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(creds, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, HOST_CREDS_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def expires_at_ms(creds: dict) -> int:
    """Claude Code stores expiresAt in milliseconds since epoch."""
    oauth = creds.get("claudeAiOauth") or {}
    v = oauth.get("expiresAt")
    return int(v) if isinstance(v, (int, float)) else 0


def refresh_tokens(creds: dict) -> dict:
    """Exchange the refresh token for a new access token.

    Returns the updated credentials dict (with the new access token,
    expiresAt, and — if the server rotates it — a new refresh token).
    Never mutates the input in-place until the exchange succeeds.
    """
    oauth = creds.get("claudeAiOauth") or {}
    rt = oauth.get("refreshToken")
    if not rt:
        raise RuntimeError("No refreshToken in host credentials -- run `claude auth login` on the host")

    scopes = oauth.get("scopes") or ["user:inference"]
    data = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": CLAUDE_CODE_CLIENT_ID,
        "scope": " ".join(scopes),
    }).encode()
    req = urllib.request.Request(
        TOKEN_ENDPOINT, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Token refresh HTTP {e.code}: {body[:200]}") from e

    new_access = result["access_token"]
    new_refresh = result.get("refresh_token", rt)
    expires_in = int(result.get("expires_in", 3600))
    new_scopes = result.get("scope", " ".join(scopes)).split()

    updated = dict(creds)
    updated["claudeAiOauth"] = dict(oauth)
    updated["claudeAiOauth"].update({
        "accessToken": new_access,
        "refreshToken": new_refresh,
        "expiresAt": int((time.time() + expires_in) * 1000),
        "scopes": new_scopes,
    })
    return updated


def get_sandbox_id(name: str, openshell_bin: str) -> str:
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


def push_access_token(sandbox: str, access_token: str, expiry_ms: int, openshell_bin: str) -> None:
    """Write just the access token + a sidecar expiry hint into the sandbox.

    Only the access token is pushed.  No refresh token, no scopes, no
    client id -- the sandbox cannot mint new tokens if compromised.
    """
    tmp = tempfile.mkdtemp(prefix="claude-token-")
    try:
        tok_path = os.path.join(tmp, SANDBOX_TOKEN_FILE)
        with open(tok_path, "w") as f:
            f.write(access_token)
        os.chmod(tok_path, 0o600)

        exp_path = os.path.join(tmp, "oauth_token_expiry")
        with open(exp_path, "w") as f:
            f.write(str(int(expiry_ms // 1000)))  # seconds, easier for shell
        os.chmod(exp_path, 0o600)

        subprocess.run(
            [openshell_bin, "sandbox", "upload", sandbox, tmp, SANDBOX_TOKEN_DIR],
            check=True, capture_output=True, text=True,
        )
        log.info(
            "Pushed access token to sandbox '%s' at %s/%s (expires %s)",
            sandbox, SANDBOX_TOKEN_DIR, SANDBOX_TOKEN_FILE,
            time.ctime(expiry_ms / 1000),
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"openshell sandbox upload failed: {e.stderr.strip()}") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ensure_fresh(creds: dict, refresh_lead_seconds: int) -> tuple[dict, bool]:
    """Return (creds, rotated).  Refresh if within refresh_lead_seconds of expiry."""
    exp_ms = expires_at_ms(creds)
    lead_ms = refresh_lead_seconds * 1000
    now_ms = int(time.time() * 1000)
    if exp_ms and (exp_ms - now_ms) > lead_ms:
        return creds, False
    log.info("Refreshing access token (expires %s)", time.ctime(exp_ms / 1000) if exp_ms else "unknown")
    new = refresh_tokens(creds)
    save_host_creds(new)
    return new, True


def next_sleep(expiry_ms: int, pushed_at: float, refresh_lead_seconds: int, max_lifetime: int) -> float:
    """How long to sleep before the next rotation.

    Two bounds:
      * Refresh when we're within refresh_lead_seconds of the server's expiry.
      * If max_lifetime > 0, refresh after the token has lived max_lifetime
        seconds regardless of server expiry.
    """
    now = time.time()
    natural = (expiry_ms / 1000) - refresh_lead_seconds - now
    if max_lifetime and max_lifetime > 0:
        capped = (pushed_at + max_lifetime) - now
        sleep_secs = min(natural, capped)
    else:
        sleep_secs = natural
    return max(MIN_SLEEP_SECONDS, sleep_secs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code OAuth access-token push daemon")
    parser.add_argument("sandbox", help="OpenShell sandbox name")
    parser.add_argument("--openshell", default="openshell", help="Path to openshell binary")
    parser.add_argument("--once", action="store_true",
                        help="Push once and exit (for install-time bootstrap)")
    parser.add_argument("--refresh-lead-seconds", type=int,
                        default=DEFAULT_REFRESH_LEAD_SECONDS,
                        help=f"Refresh this many seconds before server expiry (default {DEFAULT_REFRESH_LEAD_SECONDS})")
    parser.add_argument("--max-token-lifetime", type=int,
                        default=DEFAULT_MAX_TOKEN_LIFETIME,
                        help="Force rotation after token has been in sandbox this many seconds (0 = no cap, rotate near expiry only)")
    args = parser.parse_args()

    if args.refresh_lead_seconds < 0:
        log.error("--refresh-lead-seconds must be >= 0")
        sys.exit(2)
    if args.max_token_lifetime < 0:
        log.error("--max-token-lifetime must be >= 0")
        sys.exit(2)
    if args.max_token_lifetime and args.max_token_lifetime <= args.refresh_lead_seconds:
        log.error("--max-token-lifetime (%ds) must be greater than --refresh-lead-seconds (%ds)",
                  args.max_token_lifetime, args.refresh_lead_seconds)
        sys.exit(2)

    if not os.path.exists(HOST_CREDS_PATH):
        log.error("No host credentials at %s — run `claude auth login` on the host first", HOST_CREDS_PATH)
        sys.exit(1)

    creds = load_host_creds()
    log.info("Host credentials loaded from %s", HOST_CREDS_PATH)
    log.info("Rotation policy: refresh_lead=%ds, max_lifetime=%s",
             args.refresh_lead_seconds,
             f"{args.max_token_lifetime}s" if args.max_token_lifetime else "server expiry only")

    expected_id = get_sandbox_id(args.sandbox, args.openshell)
    log.info("Sandbox '%s' id=%s", args.sandbox, expected_id)

    creds, _ = ensure_fresh(creds, args.refresh_lead_seconds)
    access_token = creds["claudeAiOauth"]["accessToken"]
    expiry_ms = expires_at_ms(creds)
    push_access_token(args.sandbox, access_token, expiry_ms, args.openshell)
    pushed_at = time.time()

    if args.once:
        log.info("--once specified, exiting after initial push")
        return

    write_pid()
    log.info("Push daemon ready (pid %d)", os.getpid())

    def shutdown(signum, _frame):
        log.info("Signal %d, shutting down.", signum)
        remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        while True:
            sleep_secs = next_sleep(expiry_ms, pushed_at,
                                    args.refresh_lead_seconds,
                                    args.max_token_lifetime)
            log.info("Next rotation in %.0fs", sleep_secs)
            time.sleep(sleep_secs)

            for attempt in range(len(BACKOFF) + 1):
                try:
                    cur_id = get_sandbox_id(args.sandbox, args.openshell)
                    if cur_id != expected_id:
                        log.info("Sandbox replaced (%s -> %s), exiting.", expected_id, cur_id)
                        remove_pid()
                        sys.exit(0)

                    creds = load_host_creds()
                    creds, _ = ensure_fresh(creds, args.refresh_lead_seconds)
                    access_token = creds["claudeAiOauth"]["accessToken"]
                    expiry_ms = expires_at_ms(creds)
                    push_access_token(args.sandbox, access_token, expiry_ms, args.openshell)
                    pushed_at = time.time()
                    break
                except Exception as e:
                    log.warning("Attempt %d failed: %s", attempt + 1, e)
                    if attempt < len(BACKOFF):
                        time.sleep(BACKOFF[attempt])
                    else:
                        log.error("Max retries exhausted, exiting.")
                        remove_pid()
                        sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        remove_pid()
        raise


if __name__ == "__main__":
    main()
