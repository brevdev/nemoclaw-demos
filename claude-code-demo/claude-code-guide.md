# Claude Code Integration for NemoClaw

Turn your NemoClaw sandbox into a chat-driven coding workspace. Ask through Telegram, the TUI, Discord, or any channel you've wired up — "build me a FastAPI for X," "add dark mode to my todo app," "push it to GitHub" — and a sandboxed [Claude Code](https://www.anthropic.com/claude-code) worker writes the project, tests it, iterates, and reports back. Builds run in the background so the agent stays responsive while work happens; you can chat about other things and get a notification when it's done.

The integration is designed so that **no long-lived credentials ever enter the sandbox**. Claude's OAuth refresh token (SSO mode) or your Anthropic API key (API-key mode) stays on the host, and so does your GitHub PAT. The sandbox only ever sees short-lived, rotating access tokens or a pointer to a host-bound proxy.

## Prerequisites

- A working [NemoClaw](https://github.com/tklawa-nvidia/nemoclaw) install with an active OpenShell sandbox
- Node.js available inside the sandbox (Claude Code is installed via npm)
- An Anthropic account with Claude Code access — either:
  - **SSO** (recommended): any IdP Claude Code supports — NVIDIA Google Workspace, a `claude.ai` subscription, etc.
  - **API key**: a personal `sk-ant-...` key from `console.anthropic.com/settings/keys` (for users without Claude Code SSO access)
- *(Optional)* a GitHub account and a fine-grained PAT if you want the agent to push projects

## Quick Start

```bash
cd claude-code-demo
./install.sh
```

The installer walks you through:

1. Picking your auth mode (SSO — recommended — or Anthropic API key)
2. Choosing an approval mode (auto-approve or ask-on-each-command)
3. Selecting a token-rotation policy (SSO only; default: every 2 hours — see [Security](#security-overview))
4. *(Optional)* wiring up GitHub with a username + PAT
5. Installing the Claude Code CLI and uploading it into the sandbox
6. Starting the host-side auth component — the SSO push daemon or the API-key proxy — plus the GitHub proxy
7. Applying the sandbox network policies
8. Deploying the OpenClaw skill that teaches the agent how to drive Claude Code

After it finishes, just connect to your sandbox and start asking for things.

## Usage

```
"Build me a todo list app"
"Create a FastAPI REST API with JWT auth"
"Write a CLI that converts CSV to JSON"
"List my projects"
"Show me the todo-app"
"Add dark mode to my todo-app"
"Push the todo-app to GitHub"
"What's the status of my build?"
```

Projects live at `/sandbox/claude-projects/<name>/`. Each one gets its own directory with a README, `.gitignore`, and an initialized git repo.

## How builds run

Builds are **fire-and-forget background jobs**, so the OpenClaw agent stays responsive and can orchestrate many projects at once from a single chat.

When you ask for a build, the agent calls `claude-runner.sh --background --project <name> --prompt '…'`, which:

1. Creates an isolated workspace for that project
2. Launches Claude Code detached (`nohup`) with its own PID
3. Writes a status file so progress is inspectable
4. Returns immediately — the agent replies in chat and ends its turn
5. A watcher process waits for the build and notifies you through the gateway when it finishes, on whatever channel you're on (Telegram, Discord, TUI, …)

Because every job is self-contained, the agent can kick off several builds in parallel:

```
User (chat)
    │
    ▼
OpenClaw agent ──► claude-runner --background --project todo-app   ─► Claude Code #1 ─► "done" notification
              ├──► claude-runner --background --project fastapi     ─► Claude Code #2 ─► "done" notification
              └──► claude-runner --background --project csv-tool    ─► Claude Code #3 ─► "done" notification
```

Each build gets its own slice:

| Per-project | Location |
|---|---|
| Workspace | `/sandbox/claude-projects/<project>/` |
| Log | `/sandbox/.config/claude-code/logs/<project>-<timestamp>.log` |
| Status | `/sandbox/.config/claude-code/status/<project>.json` |
| Process | its own PID, nohup'd background |

All concurrent builds share one thing — the single short-lived OAuth token the host daemon keeps fresh — so auth is a shared resource but the work is fully independent. Updates (`"add dark mode to my todo-app"`) use `--continue` inside the project's own directory, so Claude Code resumes that project's session rather than the most recent one globally.

Inspect what's running:

```bash
# All builds at a glance
/sandbox/.config/claude-code/claude-runner.sh --status-all

# Detail on one build (last 10 log lines, exit code, etc.)
/sandbox/.config/claude-code/claude-runner.sh --status <project>

# See the finished project (file tree + README)
/sandbox/.config/claude-code/claude-runner.sh --result <project>
```

The only ceiling on concurrency is your Anthropic account's rate/usage limits — nothing in the architecture serializes builds.

## Security Overview

The integration runs untrusted code — Claude Code plus whatever it generates — inside the sandbox. The design goal is that a complete sandbox compromise must **not** become a long-lived account compromise. Two Anthropic auth modes are supported; both keep the long-lived secret on the host.

### SSO mode (recommended)

```
           HOST (trusted)                          │         SANDBOX (untrusted)
                                                   │
 ┌────────────────────────────────┐                │
 │ ~/.claude/.credentials.json    │                │
 │  • accessToken                 │                │
 │  • refreshToken   ◄──── never leaves host       │
 │  • scopes, expiresAt           │                │
 └──────────────┬─────────────────┘                │
                │ reads & atomically rewrites      │
                ▼                                  │
 ┌────────────────────────────────┐  refresh via   │
 │ claude-push-daemon.py          │  platform.     │
 │  • near expiry or every N hrs  │  claude.com    │
 │  • pushes ONLY accessToken ────┼──────────────► │  /sandbox/.openclaw-data/
 └────────────────────────────────┘                │     claude-code/oauth_token
                                                   │            │
                                                   │            ▼
                                                   │      claude-runner.sh
                                                   │      exports as
                                                   │      CLAUDE_CODE_OAUTH_TOKEN
                                                   │            │
                                                   │            ▼
                                                   │        claude CLI
                                                   │   (refreshToken:null —
                                                   │     cannot refresh)
```

### API-key mode (for users without Claude Code SSO)

```
           HOST (trusted)                          │         SANDBOX (untrusted)
                                                   │
 ┌────────────────────────────────┐                │
 │ ~/.nemoclaw/credentials.json   │                │
 │  • ANTHROPIC_API_KEY           │                │
 │                   ◄──── never leaves host       │
 └──────────────┬─────────────────┘                │
                │ read per request                 │
                ▼                                  │
 ┌────────────────────────────────┐                │   ANTHROPIC_BASE_URL=
 │ claude-proxy.py (127.0.0.1)    │ ◄──────────────┼──  http://<host>:9202
 │  • injects x-api-key           │                │   ANTHROPIC_API_KEY=
 │  • /v1/** allow-list only      │                │     openshell-managed
 │  • forwards to api.anthropic   │                │            │
 └──────────────┬─────────────────┘                │            ▼
                │                                  │        claude CLI
                ▼                                  │
         api.anthropic.com                         │
```

GitHub access in both modes follows the same pattern — `github-proxy.py` on `127.0.0.1` gates each request with an HMAC header and injects the PAT; the PAT itself stays in `~/.nemoclaw/credentials.json`.

### Key properties

- **Long-lived secrets stay on the host.** The Claude refresh token (SSO) or `sk-ant-…` key (API-key) lives only on the host. The GitHub PAT lives in `~/.nemoclaw/credentials.json`. None of these files are ever copied into the sandbox.
- **The sandbox can't re-auth.** In SSO mode Claude Code runs with `CLAUDE_CODE_OAUTH_TOKEN` set, so its internal state has `refreshToken:null`. In API-key mode the sandbox only ever has a dummy `ANTHROPIC_API_KEY=openshell-managed` placeholder — the real key is added by the proxy on the way out.
- **Time-bounded blast radius (SSO).** A host-side daemon rotates the access token on a configurable interval (default every 2 hours). A compromised sandbox gets at most that window of Claude API access; the next rotation invalidates any token the attacker grabbed.
- **Kill-switch (API-key).** `kill $(cat ~/.nemoclaw/claude-proxy.pid)` instantly cuts all Claude traffic from the sandbox without touching the key.
- **GitHub access is proxied.** Git requests from the sandbox route through a host-side forward proxy bound to `127.0.0.1` and gated by an HMAC header. The proxy injects the PAT on the way out, so the sandbox never sees it.
- **Fail-closed.** If the daemon or proxy stops, Claude Code in the sandbox stops working — it cannot silently limp along on stale credentials.
- **Network-scoped.** OpenShell policies restrict the sandbox to the host proxy (API-key mode) or a narrow allow-list of Anthropic endpoints (SSO mode), plus the local GitHub proxy. There's no general outbound internet access.

### Rotation policy (SSO mode)

| Option | `max_token_lifetime` | Worst-case compromise window |
|--------|----------------------|------------------------------|
| **Every 2 hours (default)** | `7200` | ≤ 2 h |
| Hourly                      | `3600` | ≤ 1 h |
| Near server expiry (~8 h)   | `0`    | ≤ 8 h |
| Custom                      | ≥ `1800` | your choice |

Picked at install time, saved to `~/.nemoclaw/claude-code-config.json`, changeable by editing that file and rerunning `./setup.sh`. 2 hours is the recommended default: it's a 4× reduction in the worst-case window versus the server's 8 h expiry, at negligible extra refresh cost, and long enough not to rotate mid-task.

## Management

```bash
# SSO mode — view push daemon
tail -f /tmp/claude-push-daemon.log
cat ~/.nemoclaw/claude-push-daemon.pid

# API-key mode — view Claude API proxy
tail -f /tmp/claude-proxy.log
cat ~/.nemoclaw/claude-proxy.pid
curl http://localhost:9202/health

# GitHub proxy
tail -f /tmp/github-proxy.log
curl http://localhost:9203/health

# Re-deploy after a host reboot or sandbox reset
./setup.sh

# Full reinstall (re-runs the interactive installer)
./install.sh

# Stop the background services (use whichever are applicable)
kill "$(cat ~/.nemoclaw/claude-push-daemon.pid)"   # SSO only
kill "$(cat ~/.nemoclaw/claude-proxy.pid)"         # API-key only
kill "$(cat ~/.nemoclaw/github-proxy.pid)"
```

`setup.sh` is the "after reboot" script — it restarts the proxy and daemon, re-uploads the runner into the sandbox, reapplies the network policies, and redeploys the skill. Use it instead of `install.sh` when the credentials and config are already in place.

---

### Credit

Created by **Tim Klawa** ([@tklawa-nvidia](https://github.com/tklawa-nvidia/))
