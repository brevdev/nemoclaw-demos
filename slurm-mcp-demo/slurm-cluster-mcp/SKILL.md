---
name: slurm-cluster-mcp
description: Connect to and interact with a fake Slurm HPC cluster via an MCP (Model Context Protocol) server using natural language. Use when the user wants to query GPU partitions, submit training/batch jobs, check running jobs, view account limits or compute usage on the simulated cluster. Trigger keywords — slurm, cluster, GPU partition, submit job, batch job, HPC, compute usage, MCP cluster, training job, cluster agent.
---

# Slurm Cluster MCP

## Overview

Provide a natural-language interface to a fake Slurm HPC cluster through an MCP server. The bundled client script (`scripts/mcp_client.py`) connects to the remote MCP server and exposes a `cluster_agent` tool that accepts plain-English queries about partitions, jobs, accounts, and usage.

## Quick Start

### 1. Install dependencies

```bash
pip install fastmcp colorama python-dotenv
```

### 2. Determine the server URL

Resolve the MCP server address in this order:

| Priority | Source | Example |
|----------|--------|---------|
| 1 | `--server-url` CLI flag | `--server-url http://192.168.1.10:8000/mcp` |
| 2 | `MCP_SERVER_URL` env var | `export MCP_SERVER_URL=http://10.0.0.5:8000/mcp` |
| 3 | Default (OpenShell) | `http://host.openshell.internal:9000/mcp` |
| 4 | Default (Docker) | `http://host.docker.internal:8000/mcp` |

### 3. Launch the interactive REPL

```bash
python <skill_dir>/scripts/mcp_client.py --server-url <URL>
```

This opens a `cluster>` prompt. Type natural-language queries and get responses.

## Programmatic Usage

To call the cluster from a script instead of the REPL, use the `ask_cluster` async function directly:

```python
import asyncio
from mcp_client import ask_cluster

result = asyncio.run(ask_cluster("http://host:8000/mcp", "show running jobs"))
print(result)
```

## Common Tasks

### Query available resources
- "what GPU partitions are available?"
- "how many nodes are in the cluster?"

### Submit jobs
- "launch a training job with 4 GPUs for 10 epochs using vit-large"
- "submit my train_bert.sh as a batch job"

### Monitor jobs
- "show me what jobs are running"
- "what's the status of job 12345?"

### Account & usage
- "what are my account limits?"
- "how much compute have I used this month?"

## Troubleshooting

If the client prints `Error: ... Is the server reachable at <url>?`:

1. Verify the MCP server process is running on the host
2. Check the URL is correct and the port is open
3. From the sandbox, test connectivity: `curl -s <server-url>` — any response (even an error JSON) means the network path works
4. If inside Docker/OpenShell, confirm the host alias resolves: `getent hosts host.docker.internal`

## Resources

- `scripts/mcp_client.py` — The MCP client REPL (run directly or import `ask_cluster`)
- `references/architecture.md` — Network topology, server details, and dependency list
