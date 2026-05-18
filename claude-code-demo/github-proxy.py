#!/usr/bin/env python3
"""Host-side git forward proxy for NemoClaw Claude Code integration.

Works like the Planet proxy: the sandbox sets the git remote URL to point at
this proxy (http://<host-ip>:9203/<owner>/<repo>.git). The request flows
through the OpenShell transparent proxy, which checks the network policy and
forwards it here. This proxy injects the GitHub PAT and forwards to
https://github.com/<path>.

The PAT never enters the sandbox.

Usage:
    python3 github-proxy.py [--port 9203]

Routes:
    GET/POST /<owner>/<repo>.git/*  → https://github.com/<path> + PAT
    GET /health                     → 200 "ok"
"""
import base64
import http.server
import hmac
import json
import os
import ssl
import sys
import urllib.request
import urllib.error

CREDS_PATH = os.path.expanduser("~/.nemoclaw/credentials.json")
TOKEN_PATH = os.path.expanduser("~/.nemoclaw/github-proxy-token")

_PROXY_TOKEN = None


def _load_proxy_token():
    """Load the shared auth token that callers must present."""
    global _PROXY_TOKEN
    if _PROXY_TOKEN is not None:
        return _PROXY_TOKEN
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            _PROXY_TOKEN = f.read().strip()
    return _PROXY_TOKEN


def _load_pat():
    with open(CREDS_PATH) as f:
        d = json.load(f)
    pat = d.get("GITHUB_PAT", "")
    if not pat:
        raise KeyError("GITHUB_PAT not found in credentials.json")
    return pat


class Handler(http.server.BaseHTTPRequestHandler):

    def _check_token(self):
        """Validate X-Proxy-Token header. Returns True if OK."""
        expected = _load_proxy_token()
        if not expected:
            return True
        presented = self.headers.get("X-Proxy-Token", "")
        return hmac.compare_digest(presented, expected)

    def _proxy(self, method):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return

        if not self._check_token():
            err = json.dumps({"error": "Invalid or missing X-Proxy-Token"}).encode()
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        try:
            pat = _load_pat()
        except Exception as e:
            err = json.dumps({"error": f"Credential load failed: {e}"}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        body = None
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            body = self.rfile.read(content_len)

        if self.path.startswith("/api/v3/"):
            target = f"https://api.github.com{self.path[7:]}"
        else:
            target = f"https://github.com{self.path}"

        basic = base64.b64encode(f"x-access-token:{pat}".encode()).decode()
        headers = {
            "Authorization": f"Basic {basic}",
            "User-Agent": self.headers.get("User-Agent", "git/nemoclaw-proxy"),
        }
        for hdr in ("Content-Type", "Accept", "Accept-Encoding",
                     "Git-Protocol", "Content-Encoding"):
            val = self.headers.get(hdr)
            if val:
                headers[hdr] = val

        req = urllib.request.Request(target, data=body, method=method,
                                     headers=headers)
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for key in ("Content-Type", "Cache-Control", "Expires",
                            "Pragma", "Content-Encoding"):
                    val = resp.headers.get(key)
                    if val:
                        self.send_header(key, val)
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

    def do_PUT(self):
        self._proxy("PUT")

    def do_PATCH(self):
        self._proxy("PATCH")

    def log_message(self, fmt, *args):
        ts = self.log_date_time_string()
        method = args[0] if args else "?"
        sys.stderr.write(f"{ts} {method}\n")


def main():
    global _PROXY_TOKEN
    port = 9203

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] == "--token" and i + 1 < len(args):
            _PROXY_TOKEN = args[i + 1]
            i += 2
        else:
            i += 1

    try:
        _load_pat()
    except (FileNotFoundError, KeyError) as e:
        print(f"Error: {CREDS_PATH}: {e}", file=sys.stderr)
        sys.exit(1)

    token = _load_proxy_token()
    token_status = "enabled" if token else "disabled (no token file)"

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"GitHub forward proxy on 127.0.0.1:{port} (creds: {CREDS_PATH})")
    print(f"  Auth:                   {token_status}")
    print(f"  /<owner>/<repo>.git/*   → https://github.com/... + PAT")
    print(f"  /health                 → 200 ok")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
