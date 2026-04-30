#!/usr/bin/env python3
"""Host-side API proxy for NemoClaw Claude Code integration.

Supports two authentication modes:
  1. API key mode:  reads ANTHROPIC_API_KEY from ~/.nemoclaw/credentials.json
  2. SSO mode:      reads OAuth token from ~/.claude/.credentials.json (host-side)

In both cases, the credential never enters the sandbox. The sandbox sends
requests to this proxy, which injects the real auth header before forwarding
to api.anthropic.com.

Usage:
    python3 claude-proxy.py [--port 9202] [--mode sso|apikey]

Routes:
    /v1/...    -> https://api.anthropic.com/v1/...  (with auth header)
    /health    -> 200 "ok"
"""
import http.server
import json
import os
import ssl
import sys
import urllib.request

CREDS_PATH = os.path.expanduser("~/.nemoclaw/credentials.json")
CLAUDE_CREDS_PATH = os.path.expanduser("~/.claude/.credentials.json")
CLAUDE_CONFIG_PATH = os.path.expanduser("~/.claude.json")
CONFIG_PATH = os.path.expanduser("~/.nemoclaw/claude-code-config.json")
TARGET_BASE = "https://api.anthropic.com"


def _detect_mode():
    """Determine auth mode from config or auto-detect."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        mode = cfg.get("auth_mode", "auto")
        if mode != "auto":
            return mode

    # Auto-detect: prefer API key if available, fall back to SSO
    try:
        with open(CREDS_PATH) as f:
            d = json.load(f)
        if d.get("ANTHROPIC_API_KEY"):
            return "apikey"
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if os.path.exists(CLAUDE_CREDS_PATH):
        return "sso"

    return "apikey"


def _load_apikey():
    with open(CREDS_PATH) as f:
        d = json.load(f)
    key = d.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise KeyError("ANTHROPIC_API_KEY not found in credentials.json")
    return key


def _load_sso_token():
    """Read OAuth token from Claude Code's host-side credential store."""
    if not os.path.exists(CLAUDE_CREDS_PATH):
        raise FileNotFoundError(
            f"Claude SSO credentials not found at {CLAUDE_CREDS_PATH}. "
            "Run 'claude' on the host and complete SSO login first."
        )

    with open(CLAUDE_CREDS_PATH) as f:
        creds = json.load(f)

    token = None

    # Claude Code stores OAuth under claudeAiOauth.accessToken
    if isinstance(creds.get("claudeAiOauth"), dict):
        token = creds["claudeAiOauth"].get("accessToken")

    # Fall back to flat key formats
    if not token:
        token = (
            creds.get("accessToken")
            or creds.get("access_token")
            or creds.get("token")
            or creds.get("oauthToken")
        )

    if not token:
        keys = []
        if isinstance(creds, dict):
            for k, v in creds.items():
                if isinstance(v, dict):
                    keys.append(f"{k}({','.join(v.keys())})")
                else:
                    keys.append(k)
        raise KeyError(
            f"No OAuth token found in {CLAUDE_CREDS_PATH}. "
            "Structure: " + ", ".join(keys)
        )

    return token


def _get_auth_headers(mode):
    """Return the auth headers to inject based on mode."""
    if mode == "apikey":
        key = _load_apikey()
        return {"x-api-key": key}
    elif mode == "sso":
        token = _load_sso_token()
        return {"Authorization": f"Bearer {token}"}
    else:
        raise ValueError(f"Unknown auth mode: {mode}")


def _resolve_target(path):
    if path.startswith("/v1/"):
        return TARGET_BASE + path
    return None


class Handler(http.server.BaseHTTPRequestHandler):

    def _proxy(self, method):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            mode = _detect_mode()
            self.wfile.write(f"ok (mode={mode})".encode())
            return

        target = _resolve_target(self.path)
        if not target:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Unknown route. Use /v1/... for Anthropic API.",
                "routes": ["/v1/...", "/health"],
            }).encode())
            return

        body = None
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            body = self.rfile.read(content_len)

        mode = _detect_mode()
        try:
            auth_headers = _get_auth_headers(mode)
        except Exception as e:
            err = json.dumps({
                "error": f"Credential load failed ({mode} mode): {e}",
                "hint": "For SSO: run 'claude' on the host to login. "
                        "For API key: add ANTHROPIC_API_KEY to ~/.nemoclaw/credentials.json"
            }).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        headers = dict(auth_headers)
        headers["anthropic-version"] = self.headers.get(
            "anthropic-version", "2023-06-01"
        )
        if body and self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]
        if self.headers.get("Accept"):
            headers["Accept"] = self.headers["Accept"]
        if self.headers.get("anthropic-beta"):
            headers["anthropic-beta"] = self.headers["anthropic-beta"]

        req = urllib.request.Request(
            target, data=body, method=method, headers=headers
        )

        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for hdr in ["Content-Type", "X-Request-Id"]:
                    val = resp.headers.get(hdr)
                    if val:
                        self.send_header(hdr, val)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            self.send_response(e.code)
            ct = e.headers.get("Content-Type", "application/json")
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as e:
            err = json.dumps({"error": str(e)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def log_message(self, fmt, *args):
        ts = self.log_date_time_string()
        method = args[0] if args else "?"
        sys.stderr.write(f"{ts} {method}\n")


def main():
    port = 9202
    force_mode = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] == "--mode" and i + 1 < len(args):
            force_mode = args[i + 1]
            i += 2
        else:
            i += 1

    mode = force_mode or _detect_mode()

    # Validate credentials exist before starting
    try:
        _get_auth_headers(mode)
    except Exception as e:
        print(f"Error ({mode} mode): {e}", file=sys.stderr)
        if mode == "sso":
            print(
                "Run 'claude' on this machine and complete SSO login first.",
                file=sys.stderr,
            )
        else:
            print(
                f"Add ANTHROPIC_API_KEY to {CREDS_PATH}",
                file=sys.stderr,
            )
        sys.exit(1)

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"Anthropic API proxy on 127.0.0.1:{port}")
    print(f"  Auth mode: {mode}")
    if mode == "sso":
        print(f"  SSO creds: {CLAUDE_CREDS_PATH}")
    else:
        print(f"  API key:   {CREDS_PATH}")
    print(f"  /v1/...  -> {TARGET_BASE}/v1/...")
    print(f"  /health  -> 200 ok")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
