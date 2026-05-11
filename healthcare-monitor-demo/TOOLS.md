# TOOLS.md - Healthcare Monitor Demo

Skills define how each workflow works. This file captures the deployment-specific rules that apply to every agent in this sandbox.

---

## Workspace Paths

- Shared synthetic data: `/sandbox/.openclaw/workspace/data/`
- Shared deterministic tools: `/sandbox/.openclaw/workspace/scripts/`
- Cron definition: `/sandbox/.openclaw/cron/jobs.json`
- Agent workspaces:
  - `main`: `/sandbox/.openclaw/workspace-main/`
  - `intake`: `/sandbox/.openclaw/workspace-intake/`
  - `clinical-triage`: `/sandbox/.openclaw/workspace-clinical-triage/`
  - `capacity-planner`: `/sandbox/.openclaw/workspace-capacity-planner/`
  - `payer-audit`: `/sandbox/.openclaw/workspace-payer-audit/`
  - `command-writer`: `/sandbox/.openclaw/workspace-command-writer/`

## Agent-Specific Instructions

### If you are `main`

You are the coordinator. Use `agents_list` to confirm the specialist IDs, then delegate with `sessions_spawn`.

Use explicit `agentId` every time:

```json
{
  "agentId": "clinical-triage",
  "task": "Run the triage workflow and return the top critical/high referrals with evidence."
}
```

The config allowlists these agents:

- `intake` for queue normalization and source-file checks.
- `clinical-triage` for risk ranking.
- `capacity-planner` for appointment matching and capacity gaps.
- `payer-audit` for prior authorization and audit flags.
- `command-writer` for final executive synthesis.

Do not send external messages. Do not ask specialists to write files. Gather their results and produce a concise operator-facing answer.

### If you are a specialist

You are a leaf worker. Do not call `sessions_spawn`, `sessions_send`, or `subagents`. Run only your assigned deterministic tool and return a compact result.

### Local commands

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py intake
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py triage
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py schedule
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py audit
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py watch-summary
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py agent-topology
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py blocked-lookup
```

Run `blocked-lookup` only when the user asks for the governance/egress check. The expected policy result is `Tunnel connection failed: 403 Forbidden`.
