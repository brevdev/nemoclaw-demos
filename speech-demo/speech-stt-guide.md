# NemoClaw + Parakeet Speech-to-Text: Zero-to-Hero Cookbook

This guide takes you from a fresh machine to a working speech-to-text demo in NemoClaw. By the end, your AI agent will be able to transcribe audio files using **NVIDIA Parakeet TDT 0.6B v3**.

The setup connects two components:
- **OpenClaw agent** (Nemotron Super 120B) handles conversation and uses the parakeet-stt skill
- **Parakeet STT service** (Docker, runs on the host) transcribes audio via an OpenAI-compatible API

> **No GPU required.** Parakeet runs on CPU (~30x faster than realtime) and NemoClaw uses NVIDIA cloud endpoints.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Linux machine | Brev instance, DGX, or any Docker-capable host. No GPU needed. |
| Docker | Must be installed and running. |
| NVIDIA API key | An API key (starts with `nvapi-`) for NemoClaw inference. Get one at [build.nvidia.com](https://build.nvidia.com). |

## Part 1: Install NemoClaw

``` bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
source ~/.bashrc
```

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

You should see output ending with:

```
✓ Sandbox 'my-assistant' created
✓ OpenClaw gateway launched inside sandbox
```

Verify:

``` bash
nemoclaw my-assistant status
```

You should see `Phase: Ready` and `OpenClaw: running`.

> **Non-interactive mode:**
> ``` bash
> export NEMOCLAW_NON_INTERACTIVE=1
> export NVIDIA_API_KEY=nvapi-...
> nemoclaw onboard --non-interactive --yes-i-accept-third-party-software
> ```

## Part 3: Set Variables

``` bash
SANDBOX=my-assistant              # whatever you named it in Part 2
DOCKER_CTR=openshell-cluster-nemoclaw
export NVIDIA_API_KEY=nvapi-...   # your NVIDIA API key
```

Find your host IP (the sandbox needs this to reach the Parakeet service):

``` bash
HOST_IP=$(hostname -I | awk '{print $1}')
echo $HOST_IP
```

You should see your machine's IP address (e.g. `10.0.0.5`).

## Part 4: Start the Parakeet STT Service

On the host (outside the sandbox), clone and start the Parakeet service:

``` bash
git clone https://github.com/groxaxo/parakeet-tdt-0.6b-v3-fastapi-openai.git
cd parakeet-tdt-0.6b-v3-fastapi-openai
docker compose up -d parakeet-cpu
```

This downloads and starts the Parakeet model in a Docker container on port 5092. First startup takes a few minutes to download the model.

Verify the service is running:

``` bash
docker ps --filter "name=parakeet" --format "{{.Names}} {{.Status}}"
```

You should see:

```
parakeet-cpu Up X minutes (healthy)
```

You can also open `http://localhost:5092` in a browser for a drag-and-drop transcription UI.

## Part 5: Update the OpenShell Network Policy

The sandbox cannot reach the host by default. We need to add a network policy allowing the sandbox to connect to the Parakeet service on the host.

### 5a. Export the current policy

``` bash
openshell policy get $SANDBOX --full > /tmp/raw-policy.txt
sed -n '8,$p' /tmp/raw-policy.txt > /tmp/current-policy.yaml
```

### 5b. Add a `parakeet_stt` policy block

Add the following block under `network_policies` in `/tmp/current-policy.yaml`. Replace `{HOST_IP}` with your host's IP from Part 3:

``` yaml
  parakeet_stt:
    name: parakeet_stt
    endpoints:
      - host: "{HOST_IP}"
        port: 5000
        protocol: rest
        tls: passthrough
        enforcement: enforce
        access: full
    binaries:
      - { path: /usr/local/bin/python3* }
      - { path: /usr/bin/python3* }
      - { path: /usr/local/bin/node* }
      - { path: /usr/bin/node* }
      - { path: /usr/bin/curl* }
      - { path: /bin/bash* }
      - { path: /usr/bin/bash* }
```

### 5c. Apply the updated policy

``` bash
openshell policy set --policy /tmp/current-policy.yaml $SANDBOX
```

You should see:

```
✓ Policy version N submitted (hash: ...)
```

Verify:

``` bash
openshell policy get $SANDBOX --full | grep -A 5 "parakeet"
```

You should see the `parakeet_stt` policy block with your host IP.

## Part 6: Install the Parakeet STT Skill

The skill file teaches the OpenClaw agent how to use the Parakeet API for transcription. Upload the skill into the sandbox:

The SKILL.md contains a `PARAKEET_URL` placeholder that must be replaced with the actual service URL before uploading. This tells the agent exactly where to send requests — without it, the agent may try to install Parakeet inside the sandbox.

``` bash
# Create the skill directory
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- mkdir -p /sandbox/.openclaw/skills/parakeet-stt

# Replace the placeholder with the actual URL and upload
sed "s|PARAKEET_URL|http://$HOST_IP:5092|g" speech-demo/parakeet-stt/SKILL.md | \
  docker exec -i $DOCKER_CTR \
  kubectl exec -i -n openshell $SANDBOX -c agent \
  -- sh -c 'cat > /sandbox/.openclaw/skills/parakeet-stt/SKILL.md'
```

Verify the skill was uploaded with the correct URL:

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- grep "5092" /sandbox/.openclaw/skills/parakeet-stt/SKILL.md
```

You should see curl commands with `http://<your-host-ip>:5092` (not the placeholder).

## Part 7: Test It

### Create a test audio file

You need an audio file in the sandbox workspace. The easiest way is to generate one with `espeak-ng` on the host:

``` bash
# Install espeak-ng (if not already installed)
sudo apt-get install -y espeak-ng

# Generate a speech WAV file
espeak-ng -w /tmp/test-speech.wav "Hello, this is a test of the Parakeet speech to text system."
```

You should see a file around 160KB:

```
-rw-rw-r-- 1 user user 160528 ... /tmp/test-speech.wav
```

Copy it into the sandbox:

``` bash
cat /tmp/test-speech.wav | docker exec -i $DOCKER_CTR \
  kubectl exec -i -n openshell $SANDBOX -c agent \
  -- sh -c 'cat > /sandbox/.openclaw-data/workspace/test-speech.wav'
```

Verify:

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- ls -la /sandbox/.openclaw-data/workspace/test-speech.wav
```

You should see a file larger than 10KB. You can also upload your own audio files (WAV, MP3, OGG, FLAC).

### Test the Parakeet API directly from the sandbox

Before using the agent, verify the sandbox can reach the Parakeet service:

``` bash
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- bash -c "curl -s -X POST http://$HOST_IP:5092/v1/audio/transcriptions -F 'file=@/sandbox/.openclaw-data/workspace/test-speech.wav' -F 'response_format=text'"
```

You should see a text transcription of the audio (e.g. the Gettysburg Address). If you get a connection error, check the network policy (Part 5).

### Chat with the agent

``` bash
nemoclaw $SANDBOX connect
openclaw tui
```

Then ask:

> **Transcribe the audio file at /sandbox/.openclaw-data/workspace/test-speech.wav**

The agent should use the parakeet-stt skill to call the Parakeet API and return the transcription.

Other prompts to try:

- "Transcribe /sandbox/.openclaw-data/workspace/test-speech.wav and save the result to transcript.md"
- "Generate SRT subtitles for the audio file at /sandbox/.openclaw-data/workspace/test-speech.wav"

## How It All Fits Together

```
┌──────────────────────────────────────────────────────────┐
│  User asks agent to transcribe an audio file             │
│                        │                                 │
│                        ▼                                 │
│  ┌──────────────────────────────┐                        │
│  │  OpenClaw Agent              │                        │
│  │  Nemotron Super 120B         │                        │
│  │  Uses parakeet-stt skill     │                        │
│  └──────────┬───────────────────┘                        │
│             │ curl POST /v1/audio/transcriptions          │
│             ▼                                            │
│  ┌──────────────────────────────┐ (on host, port 5092)   │
│  │  Parakeet STT Service        │                        │
│  │  NVIDIA Parakeet TDT 0.6B v3 │                        │
│  │  ONNX Runtime (CPU)          │                        │
│  └──────────┬───────────────────┘                        │
│             │                                            │
│             ▼                                            │
│  Transcription returned to agent → user                  │
└──────────────────────────────────────────────────────────┘
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Connection refused` from sandbox to Parakeet | Check network policy has the correct `HOST_IP` and port 5092. Redo Part 5. |
| `l7_decision=deny` in OpenShell logs | The sandbox policy isn't allowing traffic. Verify the `parakeet_stt` block in the policy. |
| Agent doesn't know about parakeet-stt | Verify SKILL.md was uploaded to `/sandbox/.openclaw/skills/parakeet-stt/`. |
| Agent tries to install Parakeet inside sandbox | The SKILL.md still has the `PARAKEET_URL` placeholder instead of the actual URL. Re-run the `sed` command in Part 6 to replace it with `http://<HOST_IP>:5092`. The agent reads the skill and sees installation instructions — it needs to see the hardcoded URL with "do NOT install" instead. |
| Agent hangs for 10+ minutes | Same as above — the agent is trying to clone repos, install packages, and run uvicorn inside the sandbox. Fix the SKILL.md and clear sessions: `docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent -- rm -rf /sandbox/.openclaw-data/agents/main/sessions/*` |
| Parakeet service not running | Check `docker ps --filter "name=parakeet"`. Restart with `docker compose up -d parakeet-cpu`. |
| Empty transcription | The audio file may be silence, corrupted, or in an unsupported format. Try a different file. |
| `PARAKEET_URL` not set | Verify the env var is set inside the sandbox: `echo $PARAKEET_URL` |

## Tailing Logs

``` bash
# Gateway log (inside sandbox)
docker exec $DOCKER_CTR kubectl exec -n openshell $SANDBOX -c agent \
  -- tail -f /tmp/gateway.log

# Parakeet service logs (on host)
docker logs -f $(docker ps --filter "name=parakeet" -q)
```

## Starting Over

``` bash
# Stop Parakeet
cd parakeet-tdt-0.6b-v3-fastapi-openai && docker compose down

# Destroy sandbox
nemoclaw $SANDBOX destroy --yes
nemoclaw onboard
# Repeat Parts 3–7
```

## Based On

This guide uses the [parakeet-stt community skill](https://github.com/openclaw/skills/blob/main/skills/carlulsoe/parakeet-stt/SKILL.md) from the OpenClaw skills repository, adapted into a zero-to-hero cookbook format.
