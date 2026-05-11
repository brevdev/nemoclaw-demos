---
name: healthcare-monitor-routing
description: Route synthetic healthcare operations questions to the correct OpenClaw specialist agents. Use when the user asks for a full care-backlog plan, triage, scheduling, prior authorization, audit review, recurring watch output, or governance explanation.
version: 1.0.0
metadata:
  domain: healthcare-operations-example
  tags: [routing, subagents, healthcare, operations, nemoclaw]
---

# Healthcare Monitor Routing

Use this skill when you are the `main` agent coordinating the healthcare monitor workflow.

## Available Specialists

- `intake`: queue normalization and source-data checks.
- `clinical-triage`: deterministic risk ranking from local rules.
- `capacity-planner`: slot matching and capacity gaps.
- `payer-audit`: prior authorization and audit flags.
- `command-writer`: final concise plan.

## Required Delegation Pattern

Before delegation, call `agents_list` to confirm these agents are available.

Use `sessions_spawn` with an explicit `agentId`. The allowlist is intentionally narrow even though OpenClaw 2026.3.11 does not support a `requireAgentId` config key.

Recommended full-plan sequence:

1. Spawn `intake`.
2. Spawn `clinical-triage`.
3. Spawn `capacity-planner`.
4. Spawn `payer-audit`.
5. Use `sessions_yield` if you need to wait for specialist completions.
6. Spawn or invoke `command-writer` with gathered evidence.
7. Return a brief final answer in normal assistant voice.

## Safety Rules

- Do not provide medical advice.
- Do not use real patient data.
- Do not ask specialists to write files.
- Do not send messages through external channels.
- Do not browse or call external services for normal workflow.
