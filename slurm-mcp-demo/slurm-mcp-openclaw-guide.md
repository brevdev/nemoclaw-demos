# Connecting a Fake Slurm HPC Cluster to OpenClaw via MCP

This guide walks you through connecting a simulated Slurm HPC cluster to an OpenClaw agent running inside an OpenShell sandbox. By the end, your agent will be able to query GPU partitions, submit training jobs, monitor the job queue, and check compute usage — all through natural language.

The connection uses **MCP (Model Context Protocol)**. A lightweight Python server runs on the host, exposes Slurm-like tools over HTTP, and uses an NVIDIA LLM to dispatch natural-language requests to the right tool. The OpenClaw agent inside the sandbox talks to it through an egress-approved network policy.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| NemoClaw | `nemoclaw` and `openshell` CLIs must be installed. See [NemoClaw setup](https://github.com/NVIDIA/NemoClaw). |
| NVIDIA API key | Powers the NL-to-tool dispatcher (`ChatNVIDIA`) inside the MCP server. Without it, all natural-language queries fail. Get one free at [build.nvidia.com/settings/api-keys](https://build.nvidia.com/settings/api-keys), save to `.env` as `NVIDIA_API_KEY=nvapi-...`. See ⚠️ Model Compatibility Warning below for supported models. |
| `uv` | Installed automatically by `install.sh` if missing. |

---

> **⚠️ Model Compatibility Warning**
>
> The MCP server's LLM dispatcher uses `ChatNVIDIA` from `langchain-nvidia-ai-endpoints`.
> **Only models that show the LangChain tab on their build.nvidia.com page are compatible.**
>
> When browsing models at [build.nvidia.com](https://build.nvidia.com), open the model's page
> and check the code snippet tabs at the top. If the **LangChain** tab is present (highlighted
> in the code sample area), the model works with `ChatNVIDIA`. If only Python / Node / Shell
> tabs are shown, the model is **not** compatible and will fail at runtime.
>
> The default model used in this demo is `nvidia/llama-3.3-nemotron-super-49b-v1.5`, which has the LangChain tab.
> To swap models, edit `fake_cluster_mcp_server.py` and replace the `model=` value —
> but only with a model confirmed to have the LangChain tab.

---

## One-Command Setup

### Set your NVIDIA API Key

Before running the installer, copy the env template and add your key:

```bash
cd nemoclaw-demos/slurm-mcp-demo
cp .env.template .env
```

Then open `.env` and replace the placeholder with your key:
```
NVIDIA_API_KEY="nvapi-your-key-here"
```

The installer will automatically load `NVIDIA_API_KEY` from `.env` — no further steps needed.

---

Run the installer from the repo root — it handles everything automatically:


```bash
cd nemoclaw-demos/slurm-mcp-demo
bash install.sh
```

The script will:
1. Clean up any stale MCP server processes
2. Resolve `NVIDIA_API_KEY` — from `.env`, `~/.nemoclaw/credentials.json`, or an interactive prompt
3. Run `nemoclaw onboard` if no sandbox exists yet
4. Install all Python dependencies on the host (latest versions via `uv`)
5. Start the MCP server in a persistent `tmux` session
6. Apply the sandbox network policy
7. Upload the `slurm-cluster-mcp` skill into the sandbox
8. Bootstrap the skill's Python venv inside the sandbox (`fastmcp`, `colorama`)
9. Restart the OpenClaw gateway so it discovers the new skill
10. Verify the installation (MCP server reachable, skill present, venv imports OK)

You can also pass a sandbox name directly:

```bash
bash install.sh <sandbox-name>
```

## Trying It Out

> **Use `openclaw tui` to interact with the agent.**
>
> The [OpenClaw TUI](https://docs.openclaw.ai/web/tui) runs directly in your terminal — no SSH tunnels, no port forwarding, no browser setup required. It renders tool calls, streaming output, and skill responses correctly, and shows the full agent reasoning trace.
>
> Launch it from your host terminal:
> ```bash
> openclaw tui
> ```

Once connected, verify the skill is loaded by asking the agent directly:

```
> do you have a skills to be able to query the slurm cluster ?

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
 agent main | session main (openclaw-tui) | inference/nvidia/nemotron-3-super-120b-a12b | tokens 23k/131k (17%)
```

Try these prompts:

- "What GPU partitions are available on the cluster?"
- "Launch a training job with 4 GPUs for 10 epochs using vit-large."
- "Submit my train_bert.sh as a batch job."
- "Show me what jobs are currently running."
- "What are my compute account limits?"
- "How much compute have I used this month?"

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
 agent main | session main (openclaw-tui) | inference/nvidia/nemotron-3-super-120b-a12b | tokens 21k/131k (16%)
```

## Available MCP Tools

| Tool | What it does |
|------|-------------|
| `cluster_agent` | NL dispatcher — LLM routes any plain-English query to the right tool |
| `get_hostname` | Returns the cluster headnode hostname |
| `sinfo` | Lists A100 / H100 / GB200 / CPU partitions |
| `srun` | Simulates an interactive training job with epoch logs |
| `sbatch` | Submits a fake batch job and returns a job ID |
| `squeue` | Shows the in-memory job queue |
| `sacctmgr` | Returns user account associations |
| `sreport` | Returns a fake CPU-minute utilisation report |

The LLM (`nvidia/llama-3.3-nemotron-super-49b-v1.5` via `ChatNVIDIA`) runs server-side — the sandbox client sends only text queries and receives text results. No API key is needed inside the sandbox.

## Changing the Model

To use a different model, edit the `_llm` block in `fake_cluster_mcp_server.py`:

```python
_llm = ChatNVIDIA(
    model="<model-id>",          # must have the LangChain tab on build.nvidia.com
    api_key=os.environ.get("NVIDIA_API_KEY", ""),
    temperature=1,
    top_p=1,
    max_tokens=16384,
    extra_body={
        "chat_template_kwargs": {
            "enable_thinking": True,
            "clear_thinking": False,
        }
    },
)
```

> **Reminder:** Only use models that show the **LangChain** tab on their
> [build.nvidia.com](https://build.nvidia.com) page. Models without this tab are not
> compatible with `ChatNVIDIA` and will raise errors at runtime.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Connection refused` from sandbox | Confirm the server is running: `curl http://{HOST_IP}:9000/mcp` from the host. Check firewall: `sudo ufw allow 9000`. |
| `401 Unauthorized` on the server | `NVIDIA_API_KEY` is missing or invalid — check the tmux session logs: `tmux attach -t slurm-mcp`. |
| Model error / `422 Unprocessable` | The selected model may not support `ChatNVIDIA`. Confirm the **LangChain** tab is present on the model's build.nvidia.com page. |
| `l7_decision=deny` in OpenShell logs | The sandbox policy wasn't applied or the connecting binary isn't listed. Re-run `policy set` and check the `mcp_server_host` block in `sandbox_policy.yaml`. |
| Wrong `host.openshell.internal` resolution | Set `MCP_SERVER_URL` explicitly to the host's LAN IP instead of relying on the DNS alias. |
| Agent doesn't know about Slurm | Confirm the skill was uploaded to `/sandbox/.openclaw/workspace/skills/slurm-cluster-mcp/` and restart the OpenClaw gateway. |
| `NVIDIA Endpoints endpoint validation failed` / `spawnSync curl ETIMEDOUT` during `nemoclaw onboard` | See below. |

### nemoclaw onboard: validation timeout

During `nemoclaw onboard`, step **[3/8] Configuring inference** makes a live inference call to validate the selected model. Thinking/reasoning models such as `nvidia/llama-3.3-nemotron-super-49b-v1.5` (nemotron model) can take ~10 seconds to respond on a non-streaming request, occasionally exceeding the 30-second internal timeout and producing:

```
NVIDIA Endpoints endpoint validation failed.
Chat Completions API: curl failed (exit -110): spawnSync curl ETIMEDOUT
```

**Recommended fix:** when prompted for a model, choose **option 1 — Nemotron 3 Super 120B**:

```
Cloud models:
  1) Nemotron 3 Super 120B (nvidia/nemotron-3-super-120b-a12b)   ← choose this
  2) Kimi K2.5 (moonshotai/kimi-k2.5)
  3) GLM-5 (z-ai/glm5)
  ...

Choose model [1]: 1
```

Nemotron 3 Super validates in under 5 seconds and will not hit the timeout. The MCP server (`fake_cluster_mcp_server.py`) uses its own separate model setting and is unaffected by this choice — you can continue using `z-ai/glm5` there if you prefer.

If you have already chosen GLM-5 and hit the timeout, type `retry` at the prompt. The API call usually succeeds on a second attempt when the model is warm.
