# Architecture

This repository is an OpenClaw-native multi-agent deployment for NemoClaw and OpenShell.

## Image-Baked Runtime

The runtime shape is built into the sandbox image:

- `openclaw.json` is merged into `/sandbox/.openclaw/openclaw.json` during `Dockerfile.sandbox` build.
- Shared skills are copied into `/sandbox/.openclaw/skills`.
- Per-agent workspaces are copied into `/sandbox/.openclaw/workspace-<agent-id>`.
- Synthetic data and analyzer scripts are copied into `/sandbox/.openclaw/workspace`.
- Cron jobs are copied into `/sandbox/.openclaw/cron`.

This avoids modifying OpenClaw configuration from inside a locked runtime sandbox.

## Agents

| Agent | Role | Skills | Spawn Access | Main Local Command |
|---|---|---|---|---|
| `main` | Coordinator | routing, command summary, egress governance | yes | orchestrates specialists and can run `report` |
| `intake` | Queue normalization | intake normalization | no | `care_backlog_analyzer.py intake` |
| `clinical-triage` | Risk ranking | clinical triage | no | `care_backlog_analyzer.py triage` |
| `capacity-planner` | Slot matching | capacity planning | no | `care_backlog_analyzer.py schedule` |
| `payer-audit` | Prior auth and audit | payer audit, egress governance | no | `care_backlog_analyzer.py audit` |
| `command-writer` | Final summary | command summary, egress governance | no | `care_backlog_analyzer.py report` |

## Delegation Flow

```text
main
  ├── agents_list
  ├── sessions_spawn(agentId="intake")
  ├── sessions_spawn(agentId="clinical-triage")
  ├── sessions_spawn(agentId="capacity-planner")
  ├── sessions_spawn(agentId="payer-audit")
  └── exec python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report
```

The leaf agents are intentionally bounded. They can read and execute local tools, but they cannot spawn other agents, write files, or send messages.

## Deterministic Tooling

`workspace/scripts/care_backlog_analyzer.py` is the deterministic evidence engine:

- `intake`: validates referral source data.
- `triage`: ranks referrals by local escalation rules.
- `schedule`: matches prioritized referrals to synthetic capacity.
- `audit`: checks payer rules, prior authorization, and audit flags.
- `report`: combines triage, capacity, and audit into a reviewable plan.
- `watch-summary`: creates a compact recurring operations signal.
- `blocked-lookup`: proves OpenShell blocks unapproved egress.

## Trust Boundary

OpenShell is the enforcement point for outbound network access. The included policy allows the sandbox to reach the local web app and managed inference route. The intentional external lookup remains blocked unless an operator applies an explicit allow rule.

The host-side web app is a control-plane wrapper around a small command
allowlist. It invokes `nemoclaw`, `openshell sandbox exec`, sandbox-local Python
analyzer commands, and the live `openclaw agent --agent main` plan command with
structured argument lists. Before live agent runs, it discovers the active
loopback gateway port inside the sandbox and passes
`OPENCLAW_GATEWAY_PORT=<port>` so subagent calls target the correct OpenClaw
gateway even when multiple sandboxes are present. The OpenShell policy does not
grant the browser arbitrary command execution; it only allows approved sandbox
processes to reach the host web app on port 5188.

## Endpoint Boundary

The included release profile onboards NemoClaw with the NVIDIA build provider,
routes sandbox calls through the shared OpenShell `inference.local` route, and
targets `nvidia/nemotron-3-super-120b-a12b`. Provider/model overrides are
explicit: set `NEMOCLAW_ALLOW_PROVIDER_OVERRIDE=1`, provide the matching
credential, and rebuild the sandbox. If multiple sandboxes share one OpenShell
gateway, the gateway-level inference provider is shared. Use separate gateways
for hard endpoint isolation.
