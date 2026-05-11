---
name: healthcare-governance-egress
description: Explain OpenShell policy-visible egress control for the healthcare monitor example. Use when asked about blocked lookup, network policy, sandbox governance, or why OpenShell matters.
version: 1.0.0
metadata:
  domain: healthcare-operations-example
  tags: [openshell, egress, governance, policy]
---

# Healthcare Governance Egress

For the intentional blocked-egress check, run:

```bash
python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py blocked-lookup
```

Expected blocked signal:

```text
Tunnel connection failed: 403 Forbidden
```

Explain:

- The analyzer attempted a normal HTTPS lookup to a target outside the approved policy.
- OpenShell denied the request at runtime.
- The block is observable through NemoClaw/OpenShell status and logs.
- This lets useful agents run while external access remains explicit and reviewable.

Do not ask the user to broaden policy unless they explicitly want the allow-rule example.
