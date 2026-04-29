# NemoClaw + Omni VLM Sub-Agent: Zero-to-Hero Cookbook

This guide takes you from a fresh machine to a working VLM (Vision Language Model) demo in NemoClaw. By the end, your AI agent will analyze images by delegating to a **Nemotron-3 Nano Omni Reasoning 30B** vision model.

The setup creates a two-agent system:
- **Main agent** (Nemotron Super 120B, text-only) handles conversation and delegates image tasks
- **Vision-operator sub-agent** (Nemotron Omni 30B, vision-capable) analyzes images and returns results

The main agent uses the Privacy Router at `inference.local`. The vision-operator bypasses the Privacy Router and calls the NVIDIA API directly, since the Privacy Router only serves a single text-only model.

> **No GPU required.** Both models are served via NVIDIA cloud endpoints.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Linux machine | Brev instance, DGX, or any Docker-capable host. No GPU needed. |
| Docker | Must be installed and running. |
| NVIDIA API key | An API key (starts with `nvapi-`) with access to the Omni model. Get one at [build.nvidia.com](https://build.nvidia.com). |

## Part 1: Install NemoClaw

``` bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

This installs:
- Node.js (if not present)
- NemoClaw CLI
- OpenShell CLI

Verify the install:

``` bash
nemoclaw --version
openshell --version
```

You should see something like:

```
nemoclaw v0.0.10
openshell 0.0.25
```

## Part 2: Onboard and Create a Sandbox

``` bash
nemoclaw onboard
```

When prompted:

1. **Inference**: Choose `1` (NVIDIA Endpoints)
2. **API Key**: Paste your NVIDIA API key (`nvapi-...`)
3. **Model**: Choose `1` (Nemotron 3 Super 120B)
4. **Sandbox name**: Enter a name (e.g. `my-assistant`)
5. **Policy presets**: Accept the suggested presets (pypi, npm) with `Y`

Wait for the image build and upload to finish. This takes a few minutes on first run.

You should see output ending with:

```
✓ Sandbox 'my-assistant' created
✓ OpenClaw gateway launched inside sandbox

Sandbox      my-assistant (Landlock + seccomp + netns)
Model        nvidia/nemotron-3-super-120b-a12b (NVIDIA Endpoints)
```

Save the tokenized dashboard URL it prints.

Verify the sandbox is running:

``` bash
nemoclaw my-assistant status
```

You should see `Phase: Ready` and `OpenClaw: running`.

> **Non-interactive mode:** For scripted setups, you can run:
> ``` bash
> export NEMOCLAW_NON_INTERACTIVE=1
> export NVIDIA_API_KEY=nvapi-...
> nemoclaw onboard --non-interactive --yes-i-accept-third-party-software
> ```

## Part 3: Set Variables

Everything below uses these — set them once:

``` bash
SANDBOX=my-assistant              # whatever you named it in Part 2
DOCKER_CTR=openshell-cluster-nemoclaw
export NVIDIA_API_KEY=nvapi-...   # your NVIDIA API key
```

Verify docker can reach the sandbox:

``` bash
docker exec $DOCKER_CTR kubectl get pod $SANDBOX -n openshell
```

You should see:

```
NAME           READY   STATUS    RESTARTS   AGE
my-assistant   1/1     Running   0          Xm
```

## Part 4: Update the OpenShell Network Policy

The OpenClaw gateway runs as `/usr/local/bin/node`. The default sandbox policy allows `integrate.api.nvidia.com` for `claude` and `openclaw` binaries, but **not** for `node`. Without this change, the vision-operator will fail with `LLM request timed out.` errors.

### 4a. Export the current policy

``` bash
openshell policy get $SANDBOX --full > /tmp/raw-policy.txt
```

The output includes 7 lines of metadata header. Strip them to get clean YAML:

``` bash
sed -n '8,$p' /tmp/raw-policy.txt > /tmp/current-policy.yaml
```

### 4b. Add `/usr/local/bin/node` to the `nvidia` policy block

Find the `nvidia:` section and add `node` to its `binaries` list. Before:

``` yaml
    binaries:
    - path: /usr/local/bin/claude
    - path: /usr/local/bin/openclaw
```

After:

``` yaml
    binaries:
    - path: /usr/local/bin/claude
    - path: /usr/local/bin/openclaw
    - path: /usr/local/bin/node
```

### 4c. Apply the updated policy

``` bash
openshell policy set --policy /tmp/current-policy.yaml $SANDBOX
```

You should see:

```
✓ Policy version N submitted (hash: ...)
```

Verify node is in the policy:

``` bash
openshell policy get $SANDBOX --full | grep -A 5 "nvidia:" | grep node
```

You should see:

```
    - path: /usr/local/bin/node
```

## Part 5: Patch openclaw.json

The sandbox config only has the main inference provider. We need to add:
- `nvidia-omni` provider pointing directly at the NVIDIA API
- `agents.list` defining `main` and `vision-operator`
- `agents.defaults.timeoutSeconds: 300` to prevent sub-agent announce timeouts

### 5a. Fetch the current config

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- cat /sandbox/.openclaw/openclaw.json > /tmp/remote_openclaw.json
```

You should see no output (the file is written to `/tmp/remote_openclaw.json` locally).

### 5b. Run the patch script

The patch script is at [`vlm-subagent/openclaw-patch.py`](vlm-subagent/openclaw-patch.py) in this repository. Copy it to `/tmp` and run it:

``` bash
python3 /tmp/openclaw-patch.py "$NVIDIA_API_KEY" \
  < /tmp/remote_openclaw.json > /tmp/updated_openclaw.json
```

You should see no output. Verify the patch worked:

``` bash
python3 -c "import json; c=json.load(open('/tmp/updated_openclaw.json')); print('Providers:', list(c['models']['providers'].keys())); print('Agents:', [a['id'] for a in c['agents']['list']])"
```

You should see:

```
Providers: ['inference', 'nvidia-omni']
Agents: ['main', 'vision-operator']
```

> You can also compare the result against [`vlm-subagent/openclaw-reference.json`](vlm-subagent/openclaw-reference.json).

### 5c. Push the patched config to the sandbox

``` bash
# Unlock config + hash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- chmod 644 /sandbox/.openclaw/openclaw.json
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- chmod 644 /sandbox/.openclaw/.config-hash

# Write patched config
cat /tmp/updated_openclaw.json | docker exec -i $DOCKER_CTR \
  kubectl exec -i -n openshell $SANDBOX -c agent \
  -- sh -c 'cat > /sandbox/.openclaw/openclaw.json'

# Regenerate the integrity hash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- /bin/bash -c "cd /sandbox/.openclaw && sha256sum openclaw.json > .config-hash"

# Lock everything back
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- chmod 444 /sandbox/.openclaw/openclaw.json
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- chmod 444 /sandbox/.openclaw/.config-hash
```

The gateway will hot-reload the config automatically. Wait a few seconds, then check the logs:

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- tail -3 /tmp/gateway.log
```

You should see:

```
[reload] config change detected; evaluating reload (models.providers.nvidia-omni, ...)
[reload] config hot reload applied (models.providers.nvidia-omni)
```

If you don't see the reload lines, wait a few more seconds and check again.

## Part 6: Create Auth Profiles for the Vision-Operator

The gateway strips API keys from `openclaw.json` when creating per-agent configs. The vision-operator calls the NVIDIA API directly and needs its own auth store. The main agent doesn't need one — it uses the Privacy Router.

``` bash
# Create the auth profile
cat > /tmp/auth-profiles.json << EOF
{
  "providers": {
    "nvidia-omni": {
      "apiKey": "$NVIDIA_API_KEY"
    }
  }
}
EOF

# Create the vision-operator agent directory (does not exist on a fresh sandbox)
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- mkdir -p /sandbox/.openclaw-data/agents/vision-operator/agent

# Write it to the vision-operator's agent directory
cat /tmp/auth-profiles.json | docker exec -i $DOCKER_CTR \
  kubectl exec -i -n openshell $SANDBOX -c agent \
  -- sh -c 'cat > /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json'

# IMPORTANT: Fix ownership so the gateway (runs as sandbox user) can write sessions
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- chown -R sandbox:sandbox /sandbox/.openclaw-data/agents/vision-operator
```

Verify the directory and ownership:

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- ls -la /sandbox/.openclaw-data/agents/vision-operator/agent/
```

You should see `auth-profiles.json` owned by `sandbox sandbox`:

```
-rw-r--r-- 1 sandbox sandbox  140 ... auth-profiles.json
```

> A template is also available at [`vlm-subagent/auth-profiles.template.json`](vlm-subagent/auth-profiles.template.json).

If you skip this step, the gateway will log `No API key found for provider "nvidia-omni"` and fall back to the text-only model, producing hallucinated image descriptions.

If you skip the `chown`, the gateway will fail with `EACCES: permission denied, mkdir '/sandbox/.openclaw/agents/vision-operator/sessions'` when the main agent tries to spawn the vision-operator.

## Part 7: Upload TOOLS.md

TOOLS.md teaches both agents how to handle image tasks. The main agent learns it must delegate via `sessions_spawn`, and the vision-operator learns it can use `read` directly on images.

The file is at [`vlm-subagent/TOOLS.md`](vlm-subagent/TOOLS.md) in this repository. Upload it to the sandbox workspace:

``` bash
cat /path/to/TOOLS.md | docker exec -i $DOCKER_CTR \
  kubectl exec -i -n openshell $SANDBOX -c agent \
  -- sh -c 'cat > /sandbox/.openclaw-data/workspace/TOOLS.md'
```

Verify:

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- ls -la /sandbox/.openclaw-data/workspace/TOOLS.md
```

You should see the file with ~2KB size:

```
-rw-r--r-- 1 root root 2034 ... TOOLS.md
```

## Part 8: Test It

### Download a test image

From the host, download an image into the sandbox workspace:

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- bash -c 'curl -sL "https://cataas.com/cat" -o /sandbox/.openclaw-data/workspace/cat.jpg'
```

Verify it downloaded (should be >10KB, not an HTML error page):

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- ls -la /sandbox/.openclaw-data/workspace/cat.jpg
```

You should see a file larger than 10KB:

```
-rw-r--r-- 1 root root 51395 ... cat.jpg
```

If the file is tiny (under 1KB), the download failed — try running the curl command again or use a different image source.

### Connect and chat

``` bash
nemoclaw $SANDBOX connect
openclaw tui
```

You should see the OpenClaw TUI interface with a prompt. Then ask:

> **Use the vision-operator sub-agent to describe the image at /sandbox/.openclaw-data/workspace/cat.jpg in detail**

You should see:
1. The main agent acknowledges the request and spawns the vision-operator
2. After a few seconds, a detailed description of the cat image appears
3. The status bar shows `agent main | session main (openclaw-tui) | inference/nvidia/nemotron-3-super-120b-a12b`

Other prompts to try:

- "What objects are visible in /sandbox/.openclaw-data/workspace/cat.jpg?"
- "Describe the image at /sandbox/.openclaw-data/workspace/cat.jpg and write the description to image-description.md"

## How It All Fits Together

```
┌─────────────────────────────────────────────────────┐
│  User sends message with image task                 │
│                        │                            │
│                        ▼                            │
│  ┌──────────────────────────────┐                   │
│  │  Main Agent                  │                   │
│  │  Nemotron Super 120B         │                   │
│  │  (text-only)                 │                   │
│  │  via Privacy Router          │                   │
│  │  (inference.local)           │                   │
│  └──────────┬───────────────────┘                   │
│             │ sessions_spawn                        │
│             ▼                                       │
│  ┌──────────────────────────────┐                   │
│  │  Vision-Operator Sub-Agent   │                   │
│  │  Nemotron Omni 30B           │                   │
│  │  (text + image)              │                   │
│  │  via NVIDIA API direct       │                   │
│  │  (integrate.api.nvidia.com)  │                   │
│  └──────────┬───────────────────┘                   │
│             │ read tool on image file               │
│             ▼                                       │
│  Image analysis returned to main agent → user       │
└─────────────────────────────────────────────────────┘
```

### Key paths

| Path | Purpose |
|------|---------|
| `/sandbox/.openclaw/openclaw.json` | Root-owned, read-only config |
| `/sandbox/.openclaw/.config-hash` | SHA256 integrity check |
| `/sandbox/.openclaw-data/workspace/` | Writable workspace (canonical path) |
| `/sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json` | Vision-operator API key |
| `/tmp/gateway.log` | Gateway stdout/stderr |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `LLM request timed out.` / `Connection error.` | The #1 issue. Check that `/usr/local/bin/node` is in the `nvidia` binaries list in the network policy. Redo Part 4. |
| `No API key found for provider "nvidia-omni"` | Vision-operator's `auth-profiles.json` is missing or wrong. Redo Part 6. |
| Main agent doesn't delegate to vision-operator | Verify `agents.list` in openclaw.json is correct and the gateway picked up the change. Try explicitly: "use the vision operator to analyze this image." |
| `Action send requires a target.` / `Unknown channel: webchat` | Vision-operator has `message` tool available. Ensure `"deny": ["message", "sessions_spawn"]` is set in its tools config. |
| Sub-agent announce timeout (60000ms) | `agents.defaults.timeoutSeconds` not set to 300. Re-run the patch script. |
| `EACCES: permission denied, mkdir .../vision-operator/sessions` | The vision-operator agent directory is owned by root. Run: `docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent -- chown -R sandbox:sandbox /sandbox/.openclaw-data/agents/vision-operator` |
| EISDIR error / wrong path | Agents using `/sandbox/.openclaw/workspace` (symlink) instead of `/sandbox/.openclaw-data/workspace/`. Verify TOOLS.md is present in the workspace. |
| Stale sessions / `session file locked` | Clear session data: `docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent -- rm -rf /sandbox/.openclaw-data/agents/*/sessions/*` |
| Test image is HTML / tiny file | The download URL returned an error page. Try a different source: `curl -sL "https://cataas.com/cat" -o /sandbox/.openclaw-data/workspace/cat.jpg` |

## Tailing Logs

From inside the sandbox:

``` bash
# Gateway log
tail -f /tmp/gateway.log

# Detailed JSON log
tail -f /tmp/openclaw/openclaw-$(date -u +%Y-%m-%d).log
```

## Starting Over

``` bash
nemoclaw $SANDBOX destroy --yes
nemoclaw onboard
# Repeat Parts 3–8
```

## See Also

- [**openclaw-omni-demo**](../openclaw-omni-demo/README.md) — Compact reference for the same setup with raw config files (`openclaw.json`, `policy.yaml`, `TOOLS.md`), overlay-mount instructions, and detailed log-parsing examples. Originally from [Haran Kumar's repo](https://gitlab-master.nvidia.com/hshivkumar/nemoclaw-with-omni-subagent).
