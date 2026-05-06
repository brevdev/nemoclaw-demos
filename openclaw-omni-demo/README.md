# NemoClaw + Omni Vision Sub-Agent Setup

Complete walkthrough for setting up a NemoClaw sandbox with the Nemotron-3 Nano
Omni reasoning model as a vision-capable sub-agent. The main agent (Nemotron
Super 120B, text-only) delegates image tasks to a `vision-operator` sub-agent
running the Omni model (text + image).

## What's in this directory

| File | Purpose |
|------|---------|
| `openclaw.json` | Reference config with Omni provider + agents list (for comparison) |
| `TOOLS.md` | Workspace file that teaches the main agent to delegate image tasks |
| `policy.yaml` | Patched OpenShell network policy (with `node` in nvidia binaries) |
| `scripts/apply-omni-subagent.sh` | Repeatable helper that patches policy, `openclaw.json`, auth profiles, and `TOOLS.md` |
| `scripts/fix-spark-gateway.sh` | Recovery helper for DGX Spark/restricted netns gateway crashes |

## Known-good model IDs

Use the public NVIDIA catalog IDs below:

```text
Main text model:  nvidia/nemotron-3-super-120b-a12b
Omni model:       nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```

Older demo notes used private or pre-release Omni IDs. If you see `model_not_found`
or `401` from the Omni provider, confirm the model ID and that your NVIDIA API key
has access to the Omni model.

## Step 1: Install NemoClaw

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc   # or source ~/.zshrc if you use zsh
```

Verify:

```bash
nemoclaw --version
openshell --version
```

## Step 2: Onboard an OpenClaw sandbox

```bash
nemoclaw onboard
```

When prompted:

1. **Inference**: Choose `1` (NVIDIA Endpoints)
2. **API Key**: Paste your NVIDIA API key (starts with `nvapi-`)
3. **Model**: Choose `1` (Nemotron 3 Super 120B)
4. **Sandbox name**: Enter a name like `hclaw`
5. **Policy presets**: Choose "Balanced" and accept suggested `pypi` and `npm`

If you are running non-interactively, use `NEMOCLAW_SANDBOX_NAME` rather than
`--name` for older NemoClaw releases that do not expose `nemoclaw onboard --name`:

```bash
NEMOCLAW_SANDBOX_NAME=hclaw \
NEMOCLAW_NON_INTERACTIVE=1 \
NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 \
NVIDIA_API_KEY="$NVIDIA_API_KEY" \
nemoclaw onboard --fresh --non-interactive --yes-i-accept-third-party-software
```

Wait for the build + image upload to finish. Save the tokenized URL it prints.

## Step 3: Set variables

Everything below uses these — set them once:

```bash
export SANDBOX=hclaw
export DOCKER_CTR=openshell-cluster-nemoclaw
export NVIDIA_API_KEY=nvapi-...   # must have Omni access
```

NemoClaw may not leave a plaintext `~/.nemoclaw/credentials.json` on current
releases, so do not rely on sourcing that file. Keep the key in your shell only
for the setup step; the helper writes it into the vision operator's in-sandbox
auth profile and keeps it out of `openclaw.json`.

## Step 4: Apply the Omni sub-agent configuration

Run the helper from this directory:

```bash
bash scripts/apply-omni-subagent.sh
```

For fully scripted smoke tests, seed a small demo identity so the first OpenClaw
turn is not intercepted by the default `BOOTSTRAP.md` identity conversation:

```bash
SEED_DEMO_IDENTITY=1 bash scripts/apply-omni-subagent.sh
```

The helper performs the manual recipe steps safely and creates a backup directory
under `/tmp` with `UNDO.txt` instructions. It:

1. Exports the active policy, adds `/usr/local/bin/node` to the `nvidia` policy
   block if needed, and reloads the policy.
2. Patches `/sandbox/.openclaw/openclaw.json` to add:
   - provider `nvidia-omni` pointing at `https://integrate.api.nvidia.com/v1`
   - `main` + `vision-operator` entries in `agents.list`
   - sub-agent limits and a longer timeout
   - `plugins.entries.bonjour.enabled=false` because mDNS discovery is not
     required for this demo and can fail inside restricted network namespaces
3. Recomputes `/sandbox/.openclaw/.config-hash`.
4. Writes the current OpenClaw auth profile format for the vision operator:

   ```json
   {
     "version": 1,
     "profiles": {
       "nvidia-omni:default": {
         "type": "api_key",
         "provider": "nvidia-omni",
         "key": "<nvapi-key>",
         "displayName": "NVIDIA Omni"
       }
     },
     "order": {
       "nvidia-omni": ["nvidia-omni:default"]
     }
   }
   ```

5. Copies `TOOLS.md` into the workspace.
6. Creates `/sandbox/.openclaw/tasks -> /sandbox/.openclaw-data/tasks` for
   OpenClaw builds that expect a writable task-registry path.

Verify the config:

```bash
openshell sandbox exec -n "$SANDBOX" -- openclaw agents list
```

Expected:

```text
Agents:
- main (default)
  Model: inference/nvidia/nemotron-3-super-120b-a12b
- vision-operator
  Model: nvidia-omni/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```

## Step 5: Ensure the OpenClaw gateway is reachable

Check gateway health from inside the sandbox:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; openclaw gateway status'
```

If the output says `Connectivity probe: ok`, continue.

### DGX Spark / restricted netns recovery

On DGX Spark or other restricted network namespaces, a stale OpenClaw gateway can
exit with messages like:

```text
gateway closed (1006)
uv_interface_addresses returned Unknown system error
```

Run the recovery helper after `apply-omni-subagent.sh`:

```bash
bash scripts/fix-spark-gateway.sh
```

It uses the NemoClaw proxy/guard environment and starts a foreground-style
sandbox gateway in the background. Logs are in `/tmp/gateway-manual.log` inside
the sandbox; the PID is in `/tmp/gateway-manual.pid`.

## Step 6: Upload a test image

Use any JPG/PNG. This creates a tiny red test image without requiring external
URLs:

```bash
python3 - <<'PY'
import base64
from pathlib import Path
# 1x1 red PNG
png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/lk3Q3wAAAABJRU5ErkJggg=="
Path("red.png").write_bytes(base64.b64decode(png))
PY

openshell sandbox upload "$SANDBOX" red.png /sandbox/.openclaw-data/workspace/
```

If `openshell sandbox upload` does not place the file where expected, copy it
through the gateway pod directly:

```bash
docker exec -i "$DOCKER_CTR" kubectl exec -i -n openshell "$SANDBOX" -- \
  tee /sandbox/.openclaw-data/workspace/red.png < red.png > /dev/null
```

## Step 7: Verify direct Omni vision

Run the vision operator directly:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; \
   openclaw agent --agent vision-operator \
     --message "Describe the image at /sandbox/.openclaw-data/workspace/red.png in one sentence." \
     --session-id direct-vision-test --timeout 300'
```

Expected: the answer should describe a solid red image. If it falls back to the
text-only Super model or says it cannot see the image, re-check the `nvidia-omni`
auth profile and model ID.

## Step 8: Verify main-agent delegation

Ask `main` to delegate to `vision-operator` and write a result file:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; \
   openclaw agent --agent main \
     --message "Use agents_list to confirm vision-operator is available, then delegate to vision-operator with sessions_spawn to describe /sandbox/.openclaw-data/workspace/red.png. Write the final one-sentence description to /sandbox/.openclaw-data/workspace/image-description.md and tell me what you wrote." \
     --session-id main-vision-delegation-test --timeout 420'
```

Confirm the file was written. Sub-agent completion is push-based, so the CLI can
return a short `completed` marker before the final write is visible; wait until
the file appears:

```bash
for _ in $(seq 1 60); do
  if openshell sandbox exec -n "$SANDBOX" --       test -s /sandbox/.openclaw-data/workspace/image-description.md; then
    openshell sandbox exec -n "$SANDBOX" --       cat /sandbox/.openclaw-data/workspace/image-description.md
    break
  fi
  sleep 1
done
```

If the first run reports a pending device scope upgrade, approve the local CLI
request and retry:

```bash
openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; openclaw devices list --json'

openshell sandbox exec -n "$SANDBOX" -- bash -lc \
  'source /tmp/nemoclaw-proxy-env.sh 2>/dev/null || true; openclaw devices approve <requestId> --json'
```

## Troubleshooting

### `401 status code` from `nvidia-omni`

Usually one of:

- `NVIDIA_API_KEY` does not have access to the Omni model
- auth profile uses the old `providers`/`apiKey` shape instead of the current
  `version` + `profiles` + `key` shape
- provider/model names do not line up (`nvidia-omni/<model-id>` in the agent,
  provider key `nvidia-omni` in `models.providers`)

Re-run:

```bash
NVIDIA_API_KEY=nvapi-... bash scripts/apply-omni-subagent.sh
```

### `LLM request timed out.` / `Connection error.`

Verify the `nvidia` policy block includes `/usr/local/bin/node`:

```bash
openshell policy get "$SANDBOX" --full | sed -n '/^  nvidia:/,/^  [a-z]/p'
```

Re-run the helper if `node` is missing.

### `gateway closed (1006)` or `uv_interface_addresses`

Run:

```bash
bash scripts/fix-spark-gateway.sh
```

Then approve any pending local CLI device scope upgrade and retry the command.

### The agent asks "Who am I?" instead of analyzing the image

The default OpenClaw workspace still has `BOOTSTRAP.md`. Either finish the
first-run identity flow in the TUI, or run:

```bash
SEED_DEMO_IDENTITY=1 bash scripts/apply-omni-subagent.sh
```

### Agent reads wrong path / EISDIR error

Use `/sandbox/.openclaw-data/workspace/`, not `/sandbox/.openclaw/workspace`.
`TOOLS.md` repeats this for both agents.

## Starting over

```bash
nemoclaw "$SANDBOX" destroy --yes
NEMOCLAW_SANDBOX_NAME="$SANDBOX" nemoclaw onboard
# Repeat steps 3-8
```
