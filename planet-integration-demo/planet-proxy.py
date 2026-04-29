#!/usr/bin/env python3
"""Host-side API proxy for NemoClaw Planet integration.

Runs on the host, reads the Planet API key from ~/.nemoclaw/credentials.json,
and proxies requests from the sandbox to Planet's API with the key injected.
The API key never enters the sandbox.

Usage:
    python3 planet-proxy.py [--port 9201]

Routes:
    /api/...   → https://api.planet.com/...   (with Authorization header)
    /tiles/... → https://tiles.planet.com/...  (with Authorization header)
    /health    → 200 "ok"
"""
import http.server
import json
import os
import sys
import urllib.request
import urllib.parse
import base64

CREDS_PATH = os.path.expanduser("~/.nemoclaw/credentials.json")

ROUTES = {
    "/api/": "https://api.planet.com/",
    "/tiles/": "https://tiles.planet.com/",
}


def _load_key():
    with open(CREDS_PATH) as f:
        d = json.load(f)
    key = d.get("PLANET_API_KEY", "")
    if not key:
        raise KeyError("PLANET_API_KEY not found in credentials.json")
    return key


def _auth_header():
    key = _load_key()
    return "Basic " + base64.b64encode((key + ":").encode()).decode()


def _resolve_target(path):
    for prefix, base in ROUTES.items():
        if path.startswith(prefix):
            return base + path[len(prefix):]
    return None


BLOCKED_POST_PREFIXES = [
    "/api/tasking/v2/orders",
]


class Handler(http.server.BaseHTTPRequestHandler):

    def _proxy(self, method):
        if method == "POST":
            for prefix in BLOCKED_POST_PREFIXES:
                if self.path.rstrip("/").startswith(prefix.rstrip("/")):
                    err = json.dumps({
                        "error": "Blocked: order creation is not permitted through this proxy",
                        "path": self.path,
                    }).encode()
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return

        target = _resolve_target(self.path)
        if not target:
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "Unknown route",
                "routes": ["/api/...", "/tiles/...", "/health"],
            }).encode())
            return

        body = None
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            body = self.rfile.read(content_len)

        try:
            auth = _auth_header()
        except Exception as e:
            err = json.dumps({"error": f"Credential load failed: {e}"}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
            return

        headers = {"Authorization": auth}
        if body and self.headers.get("Content-Type"):
            headers["Content-Type"] = self.headers["Content-Type"]

        req = urllib.request.Request(target, data=body, method=method, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                ct = resp.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ct)
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
        pass


def main():
    port = 9201
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    try:
        _load_key()
    except (FileNotFoundError, KeyError) as e:
        print(f"Error: {CREDS_PATH}: {e}", file=sys.stderr)
        sys.exit(1)

    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"Planet API proxy on 0.0.0.0:{port} (creds: {CREDS_PATH})")
    print(f"  /api/...   -> https://api.planet.com/...")
    print(f"  /tiles/... -> https://tiles.planet.com/...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
