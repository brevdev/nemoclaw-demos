# Slurm Cluster MCP — Architecture & Reference

## Overview

This skill provides a natural-language interface to a fake Slurm HPC cluster via an MCP (Model Context Protocol) server. The architecture has two components:

1. **MCP Server** — runs on the host machine, wrapping a simulated Slurm cluster with a `cluster_agent` tool
2. **MCP Client** (`scripts/mcp_client.py`) — runs in the sandbox or any network-accessible machine, connects to the server and provides an interactive REPL

## Network Topology

```
┌──────────────────────┐         HTTP/SSE          ┌──────────────────────┐
│   Sandbox / Client   │  ───────────────────────>  │   Host / MCP Server  │
│  mcp_client.py       │       POST /mcp            │  fake_cluster_mcp_   │
│                      │  <───────────────────────  │  server.py           │
└──────────────────────┘                            └──────────────────────┘
```

## Server URL Resolution Order

The client resolves the MCP server URL in this priority:

1. `--server-url` CLI flag
2. `MCP_SERVER_URL` environment variable
3. Default: `http://host.docker.internal:8000/mcp` (Docker host alias)

In OpenShell sandboxes, the default is `http://host.openshell.internal:9000/mcp`.

## MCP Tool

The server exposes a single tool:

- **Name:** `cluster_agent`
- **Parameter:** `query` (string) — natural-language request
- **Returns:** text response describing cluster state, job results, etc.

## Dependencies

- `fastmcp` — MCP client library
- `colorama` — colored terminal output
- `python-dotenv` — `.env` file loading

Install with:
```bash
pip install fastmcp colorama python-dotenv
```

## Example Queries

| Query | What it does |
|-------|-------------|
| "what GPU partitions are available?" | List available GPU partitions |
| "launch a training job with 4 GPUs for 10 epochs using vit-large" | Submit a GPU training job |
| "submit my train_bert.sh as a batch job" | Submit a batch script |
| "show me what jobs are running" | List active jobs |
| "what are my account limits?" | Show account quotas |
| "how much compute have I used this month?" | Show usage statistics |
