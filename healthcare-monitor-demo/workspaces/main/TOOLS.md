# Main Coordinator Tool Notes

Run these when direct local evidence is needed:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py agent-topology
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py watch-summary
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report
```

For the full multi-agent workflow:

1. Confirm specialists with `agents_list`.
2. Spawn `intake`, `clinical-triage`, `capacity-planner`, and `payer-audit`.
3. Send the gathered evidence to `command-writer`.
4. Return the final plan in your own voice.

Use `blocked-lookup` only for the governance egress check:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py blocked-lookup
```
