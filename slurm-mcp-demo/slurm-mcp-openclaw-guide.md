# Connecting a Fake Slurm HPC Cluster to OpenClaw via MCP

This guide walks you through connecting a simulated Slurm HPC cluster to an OpenClaw agent running inside an OpenShell sandbox. By the end, your agent will be able to query GPU partitions, submit training jobs, monitor the job queue, and check compute usage — all through natural language.

The connection uses **MCP (Model Context Protocol)**. A lightweight Python server runs on the host, exposes Slurm-like tools over HTTP, and is stateless — it requires no API key and does no LLM reasoning of its own. The OpenClaw agent inside the sandbox calls MCP tools directly and uses its configured inference model for all natural-language reasoning. The sandbox talks to the host MCP server through an egress-approved network policy.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| NemoClaw | `nemoclaw` and `openshell` CLIs must be installed. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| Inference API key | Required by `nemoclaw onboard` to configure the OpenClaw agent's inference provider. Set `INFERENCE_API_KEY` in `.env` before running `install.sh` (see below). |
| `uv` | Installed automatically by `install.sh` if missing. |

---

## One-Command Setup

### 1. Configure `.env`

Copy the template and fill in your values:

```bash
cd nemoclaw-demos/slurm-mcp-demo
cp .env.template .env
```

Open `.env` and set your API key and inference configuration. The example below uses the NVIDIA build API with Nemotron — replace these values with your own provider, base URL, and model:

```bash
# Inference API credentials
INFERENCE_API_KEY=nvapi-your-key

# Inference provider configuration
INFERENCE_PROVIDER_TYPE=nvidia
INFERENCE_PROVIDER_NAME=nvidia
INFERENCE_BASE_URL= "https://integrate.api.nvidia.com/v1"
INFERENCE_MODEL="nvidia/llama-3.3-nemotron-super-49b-v1.5"

```

> **Choosing a provider or model:** see the NemoClaw docs for the full list of supported providers, base URLs, and models:
> [https://docs.nvidia.com/nemoclaw/latest/inference/switch-inference-providers.html#switch-to-a-different-model](https://docs.nvidia.com/nemoclaw/latest/inference/switch-inference-providers.html#switch-to-a-different-model)

All five values are required. `install.sh` loads `.env` automatically — values in `.env` do not override variables already exported in your shell, so you can also override any of them inline:

```bash
INFERENCE_MODEL=nvidia/llama-3.3-70b bash install.sh
```

`INFERENCE_API_KEY` is also cached to `~/.nemoclaw/credentials.json` after the first run, so future re-runs pick it up without needing `.env` in place.

---

### 2. Run the installer

```bash
cd nemoclaw-demos/slurm-mcp-demo
bash install.sh
```

The script will:
1. Clean up any stale MCP server processes and tmux sessions
2. Load `.env` and resolve `INFERENCE_API_KEY`, provider, base URL, and model
3. Pre-configure the openshell inference provider and model
4. Run `nemoclaw onboard` if no sandbox exists — provider and model are already set, so you only need to confirm the sandbox name
5. Install all Python dependencies on the host (latest versions via `uv`)
6. Start the MCP server in a persistent `tmux` session
7. Apply the sandbox network policy (`sandbox_policy.yaml`)
8. Upload the `slurm-cluster-mcp` skill into the sandbox
9. Bootstrap the skill's Python venv inside the sandbox (`fastmcp`, `colorama`)
10. Restart the OpenClaw gateway so it discovers the new skill
11. Verify the installation (MCP server reachable, skill present, venv imports OK)

You can also pass a sandbox name directly to skip the interactive prompt:

```bash
bash install.sh <sandbox-name>
```

---

## Trying It Out

Connect to the sandbox and launch the OpenClaw TUI:

```bash
# From your host terminal
openshell sandbox connect my-assistant

# Inside the sandbox
openclaw tui
```

Once connected, verify the skill is loaded by asking the agent directly:

```
> do you have a skill to be able to query the slurm cluster?

 Yes, I have the slurm-cluster-mcp skill available, which provides a natural-language interface
 to interact with a simulated Slurm HPC cluster.

 This skill allows me to:
 - Query available resources (GPU partitions, node counts, etc.)
 - Submit training/batch jobs (like the vit-large job we just ran)
 - Monitor running jobs and check their status
 - View account limits and compute usage
 - Manage cluster operations through plain English queries

 The skill uses an MCP (Model Context Protocol) client to connect to the cluster server, and I've
 already demonstrated it working by:
 1. Checking available GPU partitions (gpu-a100, gpu-h100, gpu-gb200)
 2. Launching and monitoring a training job with 4 GPUs for 10 epochs using vit-large

 What would you like to do with the Slurm cluster? I can help you query partitions, submit jobs,
 check job status, or explore other cluster capabilities.

 connected | idle
 agent main | session main (openclaw-tui) | inference/nvidia/bedrock-claude-opus-4-6 | tokens 23k/131k (17%)
```

Try these prompts:

- "What GPU partitions are available on the cluster?"
- "Launch a training job with 4 GPUs for 10 epochs using vit-large."
- "Submit my train_bert.sh as a batch job."
- "Show me what jobs are currently running."

The session below shows the agent responding to a GPU availability query — it calls `sinfo` under the hood and summarises the A100, H100, and CPU partitions, then launches a training job:

```
openclaw tui - ws://127.0.0.1:18789 - agent main - session main

 session agent:main:main

 What GPU partitions are available on the cluster?

 Based on the Slurm cluster status, here are the available GPU partitions:

 GPU Partitions:
 - gpu-a100* (default) - 4 nodes available, idle, infinite time limit
 - gpu-h100 - 8 nodes available, idle, max 2-day time limit
 - gpu-gb200 - 2 nodes available, idle, max 4-day time limit

 There's also a cpu-general partition with 16 nodes for CPU-only workloads.

 The asterisk (*) indicates gpu-a100 is the default partition. All GPU
 partitions are currently idle and ready for jobs.


 Launch a training job with 4 GPUs for 10 epochs using vit-large.

 The training job has been successfully launched and completed. Here are
 the details:

 Job Summary:
 - Job ID: 42001
 - Resources: 4 GPUs allocated on node01
 - Time Limit: 1 hour
 - Model: vit-large
 - Epochs: 10

 Training Progress:
 The training showed steady improvement over the 10 epochs:
 - Loss decreased from 2.8051 to -0.0002
 - Accuracy increased from 0.1082 to 0.9090 (90.9%)
 - GPU utilization remained consistently high at 94%

 Completion:
 Training completed successfully. Checkpoints saved to:
 /checkpoint/user/run_42001/

 The job utilized the gpu-a100 partition (default) and finished within
 the allocated time limit.

 connected | idle
 agent main | session main (openclaw-tui) | inference/nvidia/bedrock-claude-opus-4-6 | tokens 21k/131k (16%)
```

---

## Available MCP Tools

The OpenClaw agent's LLM decides which tool to call. The MCP server exposes raw Slurm commands — it is stateless and requires no API key.

| Tool | Arguments | What it does |
|------|-----------|-------------|
| `get_hostname` | — | Returns the cluster headnode hostname |
| `sinfo` | — | Lists A100 / H100 / GB200 / CPU partitions and node states |
| `srun` | `gpus`, `time_limit`, `epochs`, `model` | Simulates an interactive training job with epoch logs |
| `sbatch` | `script_name` | Submits a fake batch job and returns a job ID |
| `squeue` | `user` | Shows the in-memory job queue |
| `sacctmgr` | `user` | Returns user account associations and limits |
| `sreport` | `user` | Returns a fake CPU-minute utilisation report |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `INFERENCE_API_KEY is not set` | Add `INFERENCE_API_KEY=your-key` to `.env`, or run `export INFERENCE_API_KEY=...` before `install.sh`. |
| `Connection refused` from sandbox | Confirm the server is running: `curl http://127.0.0.1:9000/mcp` from the host. Check logs: `tmux attach -t slurm-mcp`. |
| `l7_decision=deny` in OpenShell logs | The sandbox policy wasn't applied or the connecting binary isn't listed. Re-run `openshell policy set` and check `sandbox_policy.yaml`. |
| Wrong `host.openshell.internal` resolution | Set `MCP_SERVER_URL` explicitly to the host's LAN IP instead of relying on the DNS alias. |
| Agent doesn't know about Slurm | Confirm the skill was uploaded to `/sandbox/.openclaw/workspace/skills/slurm-cluster-mcp/` and restart the OpenClaw gateway. |
| `ModuleNotFoundError: No module named 'fastmcp'` | Run with the skill venv Python, not bare `python3`. See `SKILL.md` Troubleshooting section. |
| `NVIDIA Endpoints endpoint validation failed` / `spawnSync curl ETIMEDOUT` during `nemoclaw onboard` | See below. |

### nemoclaw onboard: validation timeout

During `nemoclaw onboard`, step **[3/8] Configuring inference** makes a live inference call to validate the pre-configured model. Thinking/reasoning models can take ~10 seconds to respond on a non-streaming request, occasionally exceeding the 30-second internal timeout and producing:

```
NVIDIA Endpoints endpoint validation failed.
Chat Completions API: curl failed (exit -110): spawnSync curl ETIMEDOUT
```

If this happens, type `retry` at the prompt — the API call usually succeeds on a second attempt when the model is warm. If the problem persists, set `INFERENCE_MODEL` in `.env` to a faster model such as `nvidia/llama-3.3-70b-instruct`.

### Restarting after a fresh reset

```bash
# Clean up everything
tmux kill-session -t slurm-mcp
openshell sandbox delete my-assistant
openshell provider delete nvidia

# Re-run
bash install.sh
```
