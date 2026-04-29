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

## Step 1: Install NemoClaw

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

## Step 2: Onboard

```bash
nemoclaw onboard
```

When prompted:
1. **Inference**: Choose `1` (NVIDIA Endpoints)
2. **API Key**: Paste your NVIDIA API key (starts with `nvapi-`)
3. **Model**: Choose `1` (Nemotron 3 Super 120B)
4. **Sandbox name**: Enter a name like `hclaw`
5. **Policy presets**: Choose "Balanced" and accept suggested (pypi, npm)

Wait for the build + image upload to finish. Save the tokenized URL it prints.

## Step 3: Set variables

Everything below uses these — set them once:

```bash
SANDBOX=hclaw
DOCKER_CTR=openshell-cluster-nemoclaw
source <(jq -r 'to_entries[] | "export \(.key)=\(.value | @sh)"' ~/.nemoclaw/credentials.json)   # loads NVIDIA_API_KEY
```

## Step 4: Update the OpenShell network policy

OpenShell's Privacy Router (`inference.local`) is currently a single-model endpoint — it
rewrites every request to the one configured model (Super 120B). For now the Omni model
must bypass the Privacy Router and call the NVIDIA API directly.

```[NOTE]
Support for multiple models in OpenShell is on the roadmap and once it lands the following section will be simplified.

See https://github.com/NVIDIA/OpenShell/issues/896 for more information.
```

The default sandbox policy allows `integrate.api.nvidia.com` and
`inference-api.nvidia.com`, but only for the `claude` and `openclaw` binaries.
**The OpenClaw gateway runs as `/usr/local/bin/node`**, so it must be added to
the nvidia policy's allowed binary list. Without this, the gateway gets silent
connection failures that surface as `LLM request timed out.` or
`Connection error.` in the logs.

### 4a. Export the current policy

```bash
openshell policy get $SANDBOX --full > /tmp/raw-policy.txt
```

The output includes 7 lines of metadata header (Version, Hash, Status, etc.)
followed by a `---` separator. Strip them to get clean YAML:

```bash
sed -n '8,$p' /tmp/raw-policy.txt > /tmp/current-policy.yaml
```

### 4b. Add `/usr/local/bin/node` to the `nvidia` policy block

Open `/tmp/current-policy.yaml` in your editor and find the `nvidia:` section and add `node` to its `binaries` list. Before:

```yaml
    binaries:
    - path: /usr/local/bin/claude
    - path: /usr/local/bin/openclaw
```

After:

```yaml
    binaries:
    - path: /usr/local/bin/claude
    - path: /usr/local/bin/openclaw
    - path: /usr/local/bin/node
```

### 4c. Apply the updated policy

Note the `--policy` flag — the file path is not positional:

```bash
openshell policy set --policy /tmp/current-policy.yaml $SANDBOX
```

You should see:

```
✓ Policy version N submitted (hash: ...)
```

Verify with:

```bash
openshell policy get $SANDBOX --full | grep -A 50 "nvidia:" | grep node
```

## Step 5: Patch openclaw.json in the sandbox

The sandbox config only has the main inference provider. We add:
- `nvidia-omni` provider pointing directly at the NVIDIA API (bypasses
  the Privacy Router, which only serves the Super 120B model)
- `agents.list` defining `main` and `vision-operator` sub-agent
- `agents.defaults.timeoutSeconds: 300` to prevent sub-agent announce timeouts

### 5a. Create the patch script

```bash
cat > /tmp/update_openclaw.py << 'PYSCRIPT'
import json, sys

config = json.load(sys.stdin)

api_key = sys.argv[1] if len(sys.argv) > 1 else "unused"

config["models"]["providers"]["nvidia"] = {
    "baseUrl": "https://integrate.api.nvidia.com/v1",
    "apiKey": api_key,
    "api": "openai-completions",
    "models": [
        {
            "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "name": "nvidia/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "reasoning": True,
            "input": ["text", "image"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 131072,
            "maxTokens": 16384
        }
    ]
}

config["agents"]["defaults"]["subagents"] = {
    "maxConcurrent": 4,
    "maxSpawnDepth": 1
}

config["agents"]["defaults"]["timeoutSeconds"] = 300

config["agents"]["list"] = [
    {
        "id": "main",
        "model": {"primary": "inference/nvidia/nemotron-3-super-120b-a12b"},
        "subagents": {"allowAgents": ["vision-operator"]},
        "tools": {"profile": "full"}
    },
    {
        "id": "vision-operator",
        "workspace": "/sandbox/.openclaw/workspace",
        "model": {"primary": "nvidia/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"},
        "tools": {
            "profile": "full",
            "deny": ["message", "sessions_spawn"]
        }
    }
]

json.dump(config, sys.stdout, indent=2)
PYSCRIPT
```

### 5b. Fetch, patch, push

```bash
# Fetch current config
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX \
  -- cat /sandbox/.openclaw/openclaw.json > /tmp/remote_openclaw.json

# Patch it (pass your NVIDIA API key as an argument)
python3 /tmp/update_openclaw.py "$NVIDIA_API_KEY" \
  < /tmp/remote_openclaw.json > /tmp/updated_openclaw.json

# Unlock config + hash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX \
  -- chmod 644 /sandbox/.openclaw/openclaw.json
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX \
  -- chmod 644 /sandbox/.openclaw/.config-hash

# Write patched config
docker exec -i $DOCKER_CTR kubectl exec -i -n openshell $SANDBOX \
  -- tee /sandbox/.openclaw/openclaw.json < /tmp/updated_openclaw.json > /dev/null

# Regenerate the integrity hash (the entrypoint checks this on startup)
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX \
  -- /bin/bash -c "cd /sandbox/.openclaw && sha256sum openclaw.json > .config-hash"

# Lock everything back
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX \
  -- chmod 444 /sandbox/.openclaw/openclaw.json
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX \
  -- chmod 444 /sandbox/.openclaw/.config-hash
```

### 5c. Create auth-profiles.json for the vision-operator

The gateway strips API keys from `openclaw.json` when creating per-agent config
files. Each agent has its own auth store at
`/sandbox/.openclaw-data/agents/<id>/agent/auth-profiles.json`. The main agent
doesn't need one (it uses the Privacy Router at `inference.local`), but the
vision-operator calls the NVIDIA API directly and needs the key.

```bash
# Create the auth profile
cat > /tmp/auth-profiles.json << EOF
{
  "providers": {
    "nvidia": {
      "apiKey": "$NVIDIA_API_KEY"
    }
  }
}
EOF

# Write it to the vision-operator's agent directory
docker exec -i $DOCKER_CTR kubectl exec -i -n openshell $SANDBOX \
  -- bash -c 'mkdir -p /sandbox/.openclaw-data/agents/vision-operator/agent/ && chown -R sandbox:sandbox /sandbox/.openclaw-data/agents/vision-operator'
  
docker exec -i $DOCKER_CTR kubectl exec -i -n openshell $SANDBOX \
  -- tee /sandbox/.openclaw-data/agents/vision-operator/agent/auth-profiles.json \
  < /tmp/auth-profiles.json > /dev/null
```

If you skip this step, the gateway will log `No API key found for provider
"nvidia-omni"` and fall back to the text-only Super 120B model, producing
hallucinated image descriptions.

## Step 6: Copy TOOLS.md into the sandbox workspace

TOOLS.md lives in the workspace directory so both agents read it as part of
their context. It contains agent-specific instructions:
- **main**: Told it's text-only, must delegate image tasks via `sessions_spawn`
- **vision-operator**: Told it CAN see images, must use `read` directly, must
  NOT try `sessions_spawn` or `message`

Both agents are told to use `/sandbox/.openclaw-data/workspace/` for all file
reads and writes.

Download the `TOOLS.md` file from this repo and copy it into the workspace.

```bash
docker exec -i $DOCKER_CTR kubectl exec -i -n openshell $SANDBOX \
  -- tee /sandbox/.openclaw-data/workspace/TOOLS.md < TOOLS.md > /dev/null
```

## Step 7: Upload test files and verify

Upload images to the workspace directory (NOT `/sandbox/` root):

```bash
wget -O doorbell.jpg https://source.roboflow.com/sOfbQhw8a0UEQ11fuaBxY45A0Wf1/0j5TIUPHOFoP4hmUlOzE/original.jpg
openshell sandbox upload $SANDBOX doorbell.jpg /sandbox/.openclaw-data/workspace/
```

From inside the sandbox (or via `openclaw tui`):

```bash
openclaw tui
```

Then ask:

> Describe the image doorbell.jpg in the workspace and write the description to image-description.md

The main agent should call `sessions_spawn` with `agentId: "vision-operator"`
rather than trying to read the image itself. The vision-operator will analyze
the image and return the result through the sessions system.

## Tailing logs

From inside the sandbox:

```bash
# Gateway log (human-readable)
tail -f /tmp/gateway.log

# Detailed JSON log
tail -f /tmp/openclaw/openclaw-$(date -u +%Y-%m-%d).log
```

From the host (requires overlay mount, see below):

```bash
sudo tail -f ~/sandbox-linked/tmp/gateway.log
```

### Reading sub-agent session logs

```bash
# List vision-operator sessions (most recent first)
ls -lt /sandbox/.openclaw-data/agents/vision-operator/sessions/*.jsonl

# Parse a session log for key events
cat /sandbox/.openclaw-data/agents/vision-operator/sessions/<session-id>.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    obj = json.loads(line.strip())
    if obj.get('type') == 'message':
        m = obj['message']
        role, err, stop = m.get('role',''), m.get('errorMessage',''), m.get('stopReason','')
        content = m.get('content','')
        if role == 'assistant':
            if isinstance(content, list):
                for c in content:
                    if c.get('type') == 'text': print(f'ASSISTANT: {c[\"text\"][:500]}')
                    elif c.get('type') == 'thinking': print(f'THINKING: {c.get(\"thinking\",\"\")[:300]}')
                    elif c.get('type') == 'toolCall': print(f'TOOL: {c.get(\"name\")} {json.dumps(c.get(\"arguments\",{}))[:200]}')
            if err: print(f'ERROR: {err}')
            if stop: print(f'STOP: {stop}')
"
```

## Troubleshooting

### "LLM request timed out." / "Connection error."

The most common cause is the **OpenShell network policy** missing
`/usr/local/bin/node` in the `nvidia` binaries list. The gateway runs as `node`
and needs explicit permission to reach `integrate.api.nvidia.com`.

Verify:
```bash
openshell policy get $SANDBOX --full | sed -n '/^  nvidia:/,/^  [a-z]/p'
```

If `node` is missing from the binaries, redo Step 4.

### "No API key found for provider nvidia-omni"

The vision-operator's `auth-profiles.json` is missing or doesn't contain the
`nvidia-omni` key. Redo Step 5c. The main agent does NOT need this file — it
uses the Privacy Router.

### "Action send requires a target." / "Unknown channel: webchat"

The vision-operator has the `message` tool available and is trying to deliver
results through an external channel. Ensure `"deny": ["message", "sessions_spawn"]`
is set in the vision-operator's tools config.

### Sub-agent announce timeouts (gateway timeout after 60000ms)

The gateway has a 60s default timeout for sub-agent announce calls. If the main
agent's LLM is busy when the announce arrives, it can time out. Setting
`agents.defaults.timeoutSeconds: 300` in `openclaw.json` raises this limit.

### Agent reads wrong path / EISDIR error

Agents may try to read `/sandbox/.openclaw/workspace` (a symlink) instead of
the canonical `/sandbox/.openclaw-data/workspace/`. The TOOLS.md file explicitly
instructs both agents to use the `-data` path. If you see path errors, verify
TOOLS.md is present and up to date in the workspace.

### Stale sessions

If you hit `session file locked` errors or the agent stops responding, clear all
session data:

```bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX \
  -- rm -rf /sandbox/.openclaw-data/agents/*/sessions/*
```

## Do NOT run `openclaw gateway restart`

The sandbox runs in a container without systemd. `openclaw gateway restart` will
kill the gateway but cannot restart it, leaving you with a dead sandbox. If the
gateway is down, destroy and recreate the sandbox (see below).

## Optional: Mount sandbox filesystem on the host

Lets you browse sandbox files from Cursor's file explorer.

```bash
# Get the sandbox container ID
CID=$(docker exec $DOCKER_CTR kubectl get pod $SANDBOX -n openshell \
  -o jsonpath='{.status.containerStatuses[0].containerID}' | sed 's|containerd://||')

# Get the overlay snapshot number
docker exec $DOCKER_CTR ctr -n k8s.io \
  -a /run/k3s/containerd/containerd.sock \
  snapshots --snapshotter overlayfs mounts / $CID
# Note the upperdir snapshot number (e.g. 86) and all lowerdir numbers

# Mount it
VOLUME=/var/lib/docker/volumes/openshell-cluster-nemoclaw/_data/agent/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots
mkdir -p ~/sandbox-linked
sudo mount -t overlay overlay \
  -o "upperdir=$VOLUME/86/fs,lowerdir=$VOLUME/82/fs:$VOLUME/81/fs:...:$VOLUME/61/fs,workdir=$VOLUME/86/work" \
  ~/sandbox-linked

# Sandbox root is at ~/sandbox-linked/sandbox/
# Config:    ~/sandbox-linked/sandbox/.openclaw/openclaw.json
# Workspace: ~/sandbox-linked/sandbox/.openclaw-data/workspace/
# Logs:      ~/sandbox-linked/tmp/gateway.log
```

This mount breaks when the pod restarts (new container = new snapshot number).
Unmount and redo if that happens:

```bash
sudo umount ~/sandbox-linked
# Re-run the steps above with the new snapshot number
```

## How it all fits together

```
Host
├── docker exec → openshell-cluster-nemoclaw (k3s cluster)
│   └── kubectl exec → hclaw pod (sandbox)
│       ├── /sandbox/.openclaw/
│       │   ├── openclaw.json      ← root-owned, read-only config
│       │   ├── .config-hash       ← SHA256 integrity check
│       │   ├── logs/              ← config audit log
│       │   └── workspace → /sandbox/.openclaw-data/workspace  (symlink)
│       ├── /sandbox/.openclaw-data/
│       │   ├── workspace/
│       │   │   ├── TOOLS.md       ← agent reads this for instructions
│       │   │   ├── AGENTS.md, SOUL.md, etc.
│       │   ├── agents/main/sessions/            ← main agent session logs
│       │   └── agents/vision-operator/
│       │       ├── agent/auth-profiles.json     ← nvidia-omni API key
│       │       └── sessions/                    ← vision-operator session logs
│       └── /tmp/
│           ├── gateway.log        ← gateway stdout/stderr
│           └── openclaw/          ← daily JSON logs
└── ~/oclaw/
    ├── openclaw.json              ← local reference config
    ├── TOOLS.md                   ← source of truth for workspace TOOLS.md
    ├── policy.yaml                ← patched OpenShell network policy
    └── README.md                  ← this file
```

### Key points

- `.openclaw/` is root-owned, read-only — always `chmod 644` before writing, `chmod 444` after
- `.openclaw-data/` is sandbox-writable — TOOLS.md goes here (via the workspace symlink)
- The entrypoint (`nemoclaw-start`) checks `.config-hash` on startup — always regenerate it
- The gateway runs as `/usr/local/bin/node` under a separate `gateway` user
- Hot-reload picks up new providers and `agents.list` when the config changes
- `inference.local` (Privacy Router) is single-model — it rewrites all requests to Super 120B
- The Omni provider bypasses the Privacy Router via a direct NVIDIA API route + network policy
- The `nvidia` network policy **must** include `/usr/local/bin/node` for the gateway to reach the API

### Config reference

| Setting | Where | Why |
|---------|-------|-----|
| `agents.defaults.timeoutSeconds: 300` | Defaults | Prevents sub-agent announce timeouts (default is 60s) |
| `agents.defaults.subagents.maxConcurrent: 4` | Defaults | Limits concurrent sub-agents |
| `agents.defaults.subagents.maxSpawnDepth: 1` | Defaults | Prevents sub-agents from spawning their own sub-agents |
| `tools.profile: "full"` | Both agents | Ensures all tools are available |
| `tools.deny: ["message", "sessions_spawn"]` | Vision-operator | Prevents external channel delivery (`message`) and re-delegation (`sessions_spawn`) |

## Starting over

```bash
nemoclaw $SANDBOX destroy --yes
nemoclaw onboard
# Repeat steps 3–7
```
