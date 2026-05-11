#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

SANDBOX="${NEMOCLAW_SANDBOX:-healthcare-monitor}"
SESSION_ID="${1:-healthcare-monitor-plan-$(date +%s%N)}"

if [[ -n "${OPENCLAW_GATEWAY_PORT:-}" ]]; then
  GATEWAY_PORT="$OPENCLAW_GATEWAY_PORT"
else
  GATEWAY_PORT="$(
    openshell sandbox exec --name "$SANDBOX" -- ss -ltnH 2>/dev/null |
      python3 -c 'import re,sys
text=sys.stdin.read()
ports=[]
for match in re.finditer(r"(?:127\.0\.0\.1|\[::1\]):(?P<port>\d+)", text):
    port=int(match.group("port"))
    if 18789 <= port < 18900 and port not in ports:
        ports.append(port)
print(sorted(ports)[0] if ports else "18789")'
  )"
fi

PROMPT="You must complete this exact tool checklist before writing any answer. 1 call agents_list. 2 call sessions_spawn once with agentId intake and ask it to run the intake workflow. 3 call sessions_spawn once with agentId clinical-triage and ask it to rank critical/high referrals. 4 call sessions_spawn once with agentId capacity-planner and ask it to schedule the queue. 5 call sessions_spawn once with agentId payer-audit and ask it to identify prior authorization and audit flags. 6 call exec with command python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report. Do not call sessions_yield. Do not wait after sessions_spawn. Ignore intermediate subagent text until all six checklist items are done. Use the exec report as the source of truth for the final answer, including payer and audit implications; do not say specialist results are pending. After item 6, answer directly in this CLI session with sections: Agent execution, Situation, Priority actions, Capacity plan, Audit/payer implications, Governance note. Synthetic data only; no medical advice. Do not call message, delivery, or channel-send tools. Return the answer directly in this CLI session only."

openshell sandbox exec --name "$SANDBOX" -- \
  env "OPENCLAW_GATEWAY_PORT=$GATEWAY_PORT" \
  openclaw agent --agent main --json \
    -m "$PROMPT" \
    --session-id "$SESSION_ID" \
    --timeout 420
