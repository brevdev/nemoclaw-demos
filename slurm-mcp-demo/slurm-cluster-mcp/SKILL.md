---
name: slurm-cluster-mcp
description: Interact with a fake Slurm HPC cluster via MCP. Provides direct tool access to query GPU partitions, submit training jobs, submit batch jobs, check the job queue, view account limits, and view compute usage. You (the agent) decide which tool to call — no secondary LLM is involved. Trigger keywords — slurm, cluster, GPU partition, submit job, batch job, HPC, compute usage, training job, sinfo, squeue, sbatch, srun.
---

# Slurm Cluster MCP

## Overview

Direct tool interface to a fake Slurm HPC cluster running on the host machine via MCP. You decide which tool to invoke based on the user's request. The MCP server exposes raw Slurm commands — call them with the specific parameters that match the user's intent.

## Invocation

Always use the skill venv's Python (required by the sandbox network policy):

```bash
SKILL_DIR=~/.openclaw/workspace/skills/slurm-cluster-mcp
$SKILL_DIR/venv/bin/python3 $SKILL_DIR/scripts/mcp_client.py <tool> [args]
```

Do **not** use bare `python3` — the system Python is not permitted to reach the MCP server on port 9000.

## Available Tools

### `get_hostname`
Returns the cluster headnode hostname.
**Use when:** user asks for the cluster name or hostname.
```bash
python3 mcp_client.py get_hostname
```

---

### `sinfo`
Lists available Slurm partitions and node states (GPU types, counts, availability).
**Use when:** user asks about available GPUs, partitions, node counts, or idle resources.
```bash
python3 mcp_client.py sinfo
```

---

### `srun`
Launches a fake interactive training job. Streams epoch-level logs and returns a job ID with checkpoint path.
**Use when:** user wants to run, launch, or start a training job interactively.
```bash
python3 mcp_client.py srun [--gpus N] [--time-limit HH:MM:SS] [--epochs N] [--model NAME]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--gpus` | int | `1` | Number of GPUs to allocate |
| `--time-limit` | str | `01:00:00` | Wall-time limit HH:MM:SS |
| `--epochs` | int | `5` | Training epochs to simulate |
| `--model` | str | `resnet50` | Model architecture name |

**Example:**
```bash
python3 mcp_client.py srun --gpus 4 --epochs 10 --model vit-large
```

---

### `sbatch`
Submits a fake batch job and returns a job ID.
**Use when:** user wants to submit a batch script.
```bash
python3 mcp_client.py sbatch [--script-name NAME]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--script-name` | str | `train.sh` | Batch script filename |

**Example:**
```bash
python3 mcp_client.py sbatch --script-name train_bert.sh
```

---

### `squeue`
Shows the current Slurm job queue.
**Use when:** user asks about running jobs, queued jobs, or job status.
```bash
python3 mcp_client.py squeue [--user NAME]
```
| Argument | Type | Default | Description |
|---|---|---|---|
| `--user` | str | `user` | Username to filter; `all` for everyone |

---

### `sacctmgr`
Shows Slurm account associations and compute limits for a user.
**Use when:** user asks about account limits, compute allocation, or account associations.
```bash
python3 mcp_client.py sacctmgr [--user NAME]
```

---

### `sreport`
Shows a cluster utilisation report (CPU-minutes used) for a user.
**Use when:** user asks about compute usage history or how much compute they have used.
```bash
python3 mcp_client.py sreport [--user NAME]
```

---

## Server URL

The client connects to `http://host.openshell.internal:9000/mcp` by default.
Override with `--server-url URL` or the `MCP_SERVER_URL` environment variable.

## Troubleshooting

If the tool call fails with a connection error:
1. Check the MCP server is running on the host: `curl http://host.openshell.internal:9000/mcp`
2. Confirm the sandbox policy is applied (allows egress to port 9000)
3. If the venv is missing, recreate it:
   ```bash
   python3 -m venv $SKILL_DIR/venv
   $SKILL_DIR/venv/bin/pip install -q fastmcp
   ```
