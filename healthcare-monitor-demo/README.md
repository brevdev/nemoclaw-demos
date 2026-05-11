# Healthcare Monitor Demo

Zero-to-hero cookbook for a multi-agent healthcare operations coordinator built on NemoClaw and OpenShell. No GPU required.

The main OpenClaw agent delegates work to five specialist subagents using `sessions_spawn`. OpenShell enforces a deny-by-default egress policy on the sandbox, so every outbound network call the agents make is explicitly governed — unapproved lookups are blocked and logged, not silently allowed.

This demo runs on a standard Linux host with Docker. It uses NVIDIA Nemotron Super via `build.nvidia.com` and requires no local GPU.

---

## What This Demo Shows

- A `main` coordinator agent that delegates to specialists via `sessions_spawn` — the OpenClaw multi-agent pattern.
- Specialist agents (`intake`, `clinical-triage`, `capacity-planner`, `payer-audit`) each have their own workspace, skills, and restricted tool permissions. Leaf agents cannot spawn further agents or write files.
- A deterministic Python CLI (`care_backlog_analyzer.py`) provides synthetic evidence for intake, triage, capacity planning, payer audit, and reporting — no live medical data involved.
- An intentional blocked-egress check that demonstrates OpenShell policy enforcement live: an outbound lookup to a non-allowlisted host returns a policy-controlled `403 Forbidden` instead of succeeding silently.
- A local web app that exposes runtime checks, agent topology, tool output, the live multi-agent plan, policy behavior, and the recurring watch job in a browser UI.
- A scheduled `Healthcare Monitor Watch` cron job that runs a condensed operations summary on a recurring interval.

All healthcare records in this repository are synthetic. The agents provide decision-support for a demonstration workflow only. They do not provide medical advice, diagnoses, or real payer determinations.

---

## Architecture

```text
Linux host
  ├── NemoClaw CLI          (nemoclaw, openshell, openclaw)
  ├── OpenShell gateway     (deny-by-default egress policy)
  └── Sandbox: healthcare-monitor   (port 18789)
       ├── openclaw.json             (agent + tool + skill config)
       ├── workspace-main/           (coordinator context)
       ├── workspace-intake/
       ├── workspace-clinical-triage/
       ├── workspace-capacity-planner/
       ├── workspace-payer-audit/
       ├── workspace-command-writer/
       ├── workspace/data/           (synthetic referral records)
       ├── workspace/scripts/        (care_backlog_analyzer.py)
       └── cron/jobs.json            (Healthcare Monitor Watch)
```

Subagent flow:

```text
main
  ├── agents_list
  ├── sessions_spawn → intake          → care_backlog_analyzer.py intake
  ├── sessions_spawn → clinical-triage → care_backlog_analyzer.py triage
  ├── sessions_spawn → capacity-planner→ care_backlog_analyzer.py schedule
  ├── sessions_spawn → payer-audit     → care_backlog_analyzer.py audit
  └── exec           → care_backlog_analyzer.py report
```

---

## Folder Layout

| Path | Purpose |
| --- | --- |
| `Dockerfile.sandbox` | Custom NemoClaw sandbox image. All config is baked in at build time. |
| `openclaw.json` | Agent topology, tool permissions, model references, plugin config. |
| `TOOLS.md` | Workspace-level operating notes injected into all agent contexts. |
| `policy.yaml` | OpenShell egress policy preset: allows localhost:5188, blocks everything else except the NVIDIA inference endpoint. |
| `workspaces/` | Per-agent context files: `AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`. |
| `skills/` | Shared OpenClaw skills with YAML frontmatter (routing, governance, command summary, payer audit). |
| `data/` | Synthetic referral records, capacity slots, payer rules, escalation rules. |
| `workspace/scripts/` | Deterministic Python CLI — the tool each specialist agent is allowed to run. |
| `openclaw-cron/` | Healthcare Monitor Watch scheduled job definition. |
| `demo-app/` | Local web application (port 5188). |
| `scripts/` | Setup, verification, policy, and packaging helpers. |
| `docs/` | Architecture, Brev walkthrough, reset, and troubleshooting references. |

---

## Requirements

- Linux host (tested on Ubuntu 24.04, GCP). Brev instances work without changes.
- Docker available to the user running NemoClaw.
- Outbound HTTPS to `https://integrate.api.nvidia.com`.
- A `build.nvidia.com` API key with access to `nvidia/nemotron-3-super-120b-a12b`.

---

## Non-Interactive Shell Note

> **Applies to Steps 5, 6, and 7.**
>
> `openshell sandbox exec` connects via gRPC streaming and by default inherits stdin from the calling shell. In a non-interactive environment — CI pipelines, scripts, Cursor agent shells, `tmux`/`screen` without an attached TTY, or SSH sessions with stdin redirected — the process will hang indefinitely waiting for stdin to close, even though the remote command completes successfully.
>
> **Fix:** append `</dev/null` to every `openshell sandbox exec` call:
>
> ```bash
> openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- <command> </dev/null
> ```
>
> Interactive terminal users (running these commands directly in a regular shell) are unaffected.

---

## Step 1 — Configure the Environment

```bash
cd ~/healthcare-monitor-demo-release/healthcare-monitor-demo
cp -n .env.example .env
chmod 600 .env
```

Edit `.env` and fill in your key and the required values:

```bash
NVIDIA_API_KEY=nvapi-<your-key>
NEMOCLAW_PROVIDER=build
NEMOCLAW_ENDPOINT_URL=https://integrate.api.nvidia.com/v1/chat/completions
NEMOCLAW_MODEL=nvidia/nemotron-3-super-120b-a12b
NEMOCLAW_ALLOW_PROVIDER_OVERRIDE=0
NEMOCLAW_SANDBOX=healthcare-monitor
NEMOCLAW_INSTALL_IF_MISSING=1
NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
NEMOCLAW_DESTROY_EXISTING=0
NEMOCLAW_APPLY_LOCAL_POLICY=1
HOST=0.0.0.0
PORT=5188
```

Keep `.env` private. It is listed in `.gitignore` and must not be copied into the sandbox image.

---

## Step 2 — Build the Sandbox

```bash
./scripts/brev-runtime-setup.sh
```

This single script handles the full setup in order:

1. Installs NemoClaw and OpenShell if not already present (`NEMOCLAW_INSTALL_IF_MISSING=1`).
2. Applies the Nemotron tool-call compatibility patch (forces `openai-completions` API for structured tool calls).
3. Runs local file verification.
4. Removes any installer-default sandbox (e.g. `my-assistant`) to ensure `healthcare-monitor` claims port 18789.
5. Builds `Dockerfile.sandbox` and runs `nemoclaw onboard`.
6. Applies the `healthcare-monitor-local` egress policy.
7. Warms up the persistent OpenClaw gateway so multi-agent coordination is ready immediately.

**Expected duration:** 15–20 min on a fresh host (NemoClaw install + Docker build). Subsequent rebuilds: 5–8 min.

**Expected final output:**
```
Policy apply complete.
Runtime setup finished.
```

Verify the sandbox is ready:

```bash
set -a && source .env && set +a
openshell sandbox list
# Expected: healthcare-monitor   Phase: Ready
```

---

## Step 3 — Verify Sandbox Status

```bash
nemoclaw "$NEMOCLAW_SANDBOX" status
```

Expected:
```
Sandbox: healthcare-monitor
Model:    nvidia/nemotron-3-super-120b-a12b
Provider: nvidia-prod
Inference: healthy (https://integrate.api.nvidia.com/v1/models)
Phase: Ready
```

---

## Step 4 — Probe the NVIDIA Endpoint

Confirms your API key and model access independently of OpenClaw:

```bash
./scripts/probe-build-endpoint.sh
```

Expected: `Endpoint probe succeeded. Model response: READY`

---

## Step 5 — Verify Tool Calling

Sends a minimal prompt through the full OpenClaw stack and forces a single `agents_list` tool call. This confirms the Nemotron tool-call patch is active and structured tool calls are working end-to-end:

```bash
openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- \
  openclaw agent --agent main --json \
    -m "Call agents_list now and return only the raw result. Do not say anything else." \
    --timeout 90 </dev/null
```

Expected: JSON output listing all 6 agents (`main`, `intake`, `clinical-triage`, `capacity-planner`, `payer-audit`, `command-writer`) with `"configured": true`.

> **Note:** You may see `Gateway agent failed; falling back to embedded` on the first call after a build. This is normal — embedded mode still executes the tool call correctly. The persistent gateway is warmed up by setup, but may need a moment on the very first connection.

---

## Step 6 — OpenClaw Smoke Tests

Confirm all agents and skills loaded correctly:

```bash
# All 6 agents present
openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- openclaw agents </dev/null

# 7 healthcare skills installed
openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- \
  sh -lc 'openclaw skills list | grep healthcare' </dev/null

# Agent topology
openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- \
  python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py agent-topology </dev/null
```

Run each deterministic specialist tool to confirm data and scripts are intact inside the sandbox:

```bash
for cmd in intake triage schedule audit report; do
  echo "=== $cmd ==="
  openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- \
    python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py $cmd </dev/null
done
```

---

## Step 7 — Run the Live Multi-Agent Plan

Runs the full orchestration: `main` → `agents_list` → 4× `sessions_spawn` → `exec report`. The script auto-discovers the active gateway port inside the sandbox:

```bash
./scripts/run-agent-plan.sh
```

> **Non-interactive shell:** `run-agent-plan.sh` uses `openshell sandbox exec` internally for both port discovery and the agent run. If calling this script from a non-TTY environment (CI, Cursor agent, script), set `OPENCLAW_GATEWAY_PORT=18789` to skip the port-discovery exec, and pipe stdin: `./scripts/run-agent-plan.sh </dev/null`.

**Allow 5–7 minutes** on first run (cold start on `build.nvidia.com`). Expected output sections:
- `Agent execution` — confirms all 6 tool calls with zero failures
- `Situation` — referral backlog summary
- `Priority actions` — critical/high referrals
- `Capacity plan` — scheduled slots
- `Audit/payer implications` — prior auth flags
- `Governance note` — OpenShell policy context

---

## Step 8 — Start the Web App

```bash
HOST=0.0.0.0 PORT=5188 ./scripts/start-demo-app.sh
```

Open `http://<host-ip>:5188` in a browser (or `http://127.0.0.1:5188` locally).

The app has five tabs:

| Tab | What it shows |
| --- | --- |
| Runtime | Sandbox status, inference health, gateway port |
| Architecture | Agent topology, workspace files, skill list |
| Evidence | Deterministic tool output for each specialist |
| Operations | Live multi-agent plan, watch summary, blocked-egress test |
| Governance | Egress policy rules, cron job config, embedded OpenShell terminal |

The Governance tab includes a live embedded terminal running `openshell term` inside the `healthcare-monitor` sandbox — you can run commands and see policy enforcement in real time.

---

## Runtime Notes

### Why a Single Sandbox

The OpenClaw CLI connects to the gateway on loopback port `18789` by default. If a second sandbox exists (e.g. an installer-default `my-assistant`), it takes port 18789 and `healthcare-monitor` falls back to port 18790 — causing `openclaw agent` to miss the gateway and use embedded mode for every call. The setup script removes any non-target sandboxes before onboarding so `healthcare-monitor` always owns port 18789.

### Nemotron Tool Calls Require `openai-completions`

The NVIDIA `build.nvidia.com` endpoint for Nemotron defaults to `/v1/responses`, which does not return structured `tool_calls` JSON. The setup script applies a compatibility patch (`patch-nemoclaw-build-provider.sh`) that switches OpenClaw to the `/v1/chat/completions` endpoint, enabling reliable `sessions_spawn`, `agents_list`, and `exec` tool calls. Verify the patch with:

```bash
grep -c "tool-call-parser" ~/.nemoclaw/source/dist/lib/onboard.js
# Expected: 5
```

### Sandbox Config Is Image-Baked

All OpenClaw configuration is baked into the Docker image at build time (Landlock enforced at runtime). Do not attempt to modify `/sandbox/.openclaw/openclaw.json` from inside the sandbox. Put config changes in the repo and rebuild with `Dockerfile.sandbox`.

### Multi-Agent Requires the Persistent Gateway

`sessions_spawn` requires the persistent OpenClaw gateway to be running — sub-agents connect back to the parent session through it. When only embedded mode is available, `sessions_spawn` calls still execute but sub-agents cannot coordinate with the parent. The setup script warms up the gateway automatically. If you need to restart it manually:

```bash
nemoclaw healthcare-monitor connect --probe-only
```

### Blocked Egress Demo

The Governance tab and `run-agent-plan.sh` both surface a blocked-egress check. The Python tool attempts a lookup to a non-allowlisted host; OpenShell policy intercepts it and returns `403 Forbidden`. The tool catches this and exits cleanly with `EGRESS_BLOCKED`. This is intentional — it is the live governance proof point.

---

## Rebuild / Reset

To fully tear down and rebuild the sandbox from scratch:

```bash
NEMOCLAW_FORCE_DESTROY_EXISTING=1 ./scripts/brev-runtime-setup.sh
```

To restart only the web app:

```bash
fuser -k 5188/tcp || true
HOST=0.0.0.0 PORT=5188 ./scripts/start-demo-app.sh
```

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `openshell sandbox exec` hangs with no output | `healthcare-monitor` is on port 18790 instead of 18789 (second sandbox occupying default port) | Rebuild: `NEMOCLAW_FORCE_DESTROY_EXISTING=1 ./scripts/brev-runtime-setup.sh` |
| `openshell sandbox exec` hangs with no output or error in a script/CI/non-interactive shell | `exec` inherits stdin from the calling shell and blocks indefinitely waiting for it to close, even after the remote command finishes | Append `</dev/null` to the command: `openshell sandbox exec --name "$SANDBOX" -- <cmd> </dev/null`. For `run-agent-plan.sh`, also set `OPENCLAW_GATEWAY_PORT=18789` to skip the port-discovery exec. |
| `sessions_spawn` called but sub-agents never return results | Persistent gateway not running; main agent in embedded mode | Run `nemoclaw healthcare-monitor connect --probe-only` to start the gateway |
| Tool calls come back as XML text instead of executing | Nemotron patch not applied or overwritten | Check: `grep -c "tool-call-parser" ~/.nemoclaw/source/dist/lib/onboard.js` → expect `5`. Rebuild if missing. |
| `Gateway agent failed; falling back to embedded` (every call, not just first) | Gateway stopped or was never started | Run `nemoclaw healthcare-monitor connect --probe-only` |
| Governance terminal shows "Failed to fetch" | Web app started in a restricted environment that blocks PTY creation | Restart with: `HOST=0.0.0.0 PORT=5188 ./scripts/start-demo-app.sh` from a regular shell |
| `Endpoint probe failed with HTTP 401` | Invalid or expired API key | Update `NVIDIA_API_KEY` in `.env` |
| Two sandboxes in `openshell sandbox list` | Installer-default sandbox not cleaned up | `nemoclaw <other-name> destroy --yes` |
| Cron job fires immediately on startup | `jobs.json` anchor is in the past | Expected — the watch summary runs once, then waits for the next interval |

---

## Package for Sharing

```bash
./scripts/package-demo.sh
```

Creates a timestamped `.zip` beside the project directory. The archive excludes `.env`, local state, caches, and generated archives. It keeps `.env.example` so a new machine can be configured from scratch.

For a stable filename:

```bash
./scripts/package-demo.sh ../healthcare-monitor-demo-release.zip
```

---

## Notes

NemoClaw and OpenClaw are evolving quickly. Treat this repository as a repeatable example architecture and validation harness, not a production medical workflow. The [NemoClaw Demos repository](https://github.com/brevdev/nemoclaw-demos) contains additional examples covering VLM subagents, speech-to-text, Google Workspace integration, Blender, and more.
