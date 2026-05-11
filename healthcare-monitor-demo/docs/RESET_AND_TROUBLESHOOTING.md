# Reset And Troubleshooting

## Quick Health Check

```bash
cd ~/healthcare-monitor-demo
set -a
source .env
set +a

./scripts/run-local-verification.sh
nemoclaw "$NEMOCLAW_SANDBOX" status
nemoclaw "$NEMOCLAW_SANDBOX" connect --probe-only
curl -fsS "http://127.0.0.1:${PORT:-5188}/api/config"
```

## Rebuild The Image-Baked Sandbox

Use the force flag for one run:

```bash
NEMOCLAW_FORCE_DESTROY_EXISTING=1 ./scripts/brev-runtime-setup.sh
```

This destroys and recreates only the sandbox named by `NEMOCLAW_SANDBOX`.

## Verify OpenClaw Config In The Sandbox

```bash
./scripts/show-sandbox-config.sh
```

## Verify Agents

```bash
openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- openclaw agents
./scripts/run-agent-plan.sh
```

## Verify The Shared Gateway Inference Route

```bash
openshell inference get
```

If multiple sandboxes share one gateway, this is the active gateway-level route. Use separate gateways for hard endpoint isolation.

## Web App Is Not Reachable

Check the listener:

```bash
ss -ltnp | grep 5188
curl -fsS "http://127.0.0.1:5188/api/config"
```

For remote browser access, the listener should be `0.0.0.0:5188`:

```bash
fuser -k 5188/tcp || true
HOST=0.0.0.0 PORT=5188 ./scripts/start-demo-app.sh
```

## Blocked Egress Does Not Appear

Expected:

```text
EGRESS_BLOCKED
reason=<urlopen error Tunnel connection failed: 403 Forbidden>
```

If the lookup succeeds, check whether `example.org:443` was explicitly approved. Remove the allow rule or rebuild the sandbox.

## OpenClaw Gateway Port Discovery

The release agent script discovers the sandbox's active OpenClaw loopback port
and passes it through `OPENCLAW_GATEWAY_PORT`:

```bash
openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- ss -ltnH
OPENCLAW_GATEWAY_PORT=18790 ./scripts/run-agent-plan.sh
```

The manual variable is useful when experimenting with direct OpenClaw CLI
commands. The web app and `./scripts/run-agent-plan.sh` handle this discovery
automatically for normal demo runs.

## Verify NVIDIA Build Inference

For the build provider, confirm both the hosted endpoint and the sandbox route:

```bash
./scripts/probe-build-endpoint.sh
openshell inference get
openshell sandbox exec --name "$NEMOCLAW_SANDBOX" -- \
  python3 /sandbox/.openclaw/workspace/scripts/care_backlog_analyzer.py report
```
