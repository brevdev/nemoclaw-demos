#!/usr/bin/env python3
"""
Fake Slurm HPC headnode — MCP server exposing raw Slurm tools.

The OpenClaw agent (which has its own LLM) decides which tool to call.
No secondary LLM or NL dispatcher runs here.

Tools exposed:
  get_hostname  — return headnode hostname
  sinfo         — show partitions / node states
  srun          — launch a fake interactive training job
  sbatch        — submit a fake batch job
  squeue        — show job queue
  sacctmgr      — show account associations
  sreport       — show utilisation report

Run:
  python fake_cluster_mcp_server.py              # streamable-http on 0.0.0.0:9000/mcp
  python fake_cluster_mcp_server.py --port 9000
"""
from __future__ import annotations

import argparse
import os
import random

from colorama import Fore, init as colorama_init
from fastmcp import FastMCP

colorama_init(autoreset=True)

mcp = FastMCP("fake-slurm-cluster")

# ---------------------------------------------------------------------------
# In-memory job table (persists for the lifetime of the server process)
# ---------------------------------------------------------------------------
_jobs: dict[int, dict] = {}
_next_job_id = 42001

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@mcp.tool()
def get_hostname() -> str:
    """Return the cluster headnode hostname."""
    return "dlcluster-headnode"


@mcp.tool()
def sinfo() -> str:
    """Show available Slurm partitions and node states."""
    return (
        "PARTITION    AVAIL  TIMELIMIT   NODES  STATE  NODELIST\n"
        "gpu-a100*    up     infinite        4  idle   node[01-04]\n"
        "gpu-h100     up     2-00:00:00      8  idle   node[05-12]\n"
        "gpu-gb200    up     4-00:00:00      2  idle   node[13-14]\n"
        "cpu-general  up     infinite       16  idle   node[15-30]\n"
    )


@mcp.tool()
def srun(
    gpus: int = 1,
    time_limit: str = "01:00:00",
    epochs: int = 5,
    model: str = "resnet50",
) -> str:
    """Launch a fake interactive training job via srun.

    Args:
        gpus: Number of GPUs to allocate.
        time_limit: Wall-time limit HH:MM:SS.
        epochs: Training epochs to simulate.
        model: Model name printed in the epoch log.
    """
    global _next_job_id
    job_id = _next_job_id
    _next_job_id += 1

    lines = [
        f"srun: job {job_id} queued and waiting for resources",
        f"srun: job {job_id} has been allocated resources",
        f"Allocated {gpus} GPU(s) on node01 | time_limit={time_limit}",
        "",
    ]
    random.seed(job_id)
    loss, acc = 3.2, 0.05
    for epoch in range(1, epochs + 1):
        loss -= random.uniform(0.2, 0.5)
        acc  += random.uniform(0.05, 0.12)
        lines.append(
            f"Epoch [{epoch}/{epochs}]  loss={loss:.4f}  "
            f"acc={min(acc, 1.0):.4f}  lr=1e-4  gpu_util=94%  model={model}"
        )
    lines += [
        "",
        f"Training complete. Checkpoints → /checkpoint/user/run_{job_id}/",
    ]
    _jobs[job_id] = {"state": "COMPLETED", "user": "user",
                     "partition": "gpu-a100", "name": model}
    return "\n".join(lines)


@mcp.tool()
def sbatch(script_name: str = "train.sh") -> str:
    """Submit a fake batch job.

    Args:
        script_name: Name of the batch script.
    """
    global _next_job_id
    job_id = _next_job_id
    _next_job_id += 1
    _jobs[job_id] = {"state": "RUNNING", "user": "user",
                     "partition": "gpu-a100", "name": script_name}
    return f"Submitted batch job {job_id}"


@mcp.tool()
def squeue(user: str = "user") -> str:
    """Show jobs in the Slurm queue.

    Args:
        user: Filter by username; "all" to see every job.
    """
    header = (
        "             JOBID PARTITION     NAME     USER  ST       TIME  NODES NODELIST\n"
    )
    rows = []
    for jid, info in _jobs.items():
        if user == "all" or info["user"] == user:
            st = "R" if info["state"] == "RUNNING" else "CG"
            rows.append(
                f"             {jid:>5}  {info['partition']:<10} "
                f"{info['name']:<8} {info['user']:<8}  {st}  0:01       1 node01"
            )
    return header + ("\n".join(rows) if rows else "(no jobs)")


@mcp.tool()
def sacctmgr(user: str = "user") -> str:
    """Show Slurm account associations for a user.

    Args:
        user: Username to query.
    """
    return (
        "   Cluster    Account       User  Partition  Share  MaxJobs        QOS\n"
        "---------- ---------- --------- ---------- ------  -------  ---------\n"
        "dlcluster        root                            1             normal\n"
        "dlcluster        root      root                  1             normal\n"
        f"dlcluster     {user:<10}                    1             normal\n"
        f"dlcluster     {user:<10} {user:<9}            1      200    normal\n"
    )


@mcp.tool()
def sreport(user: str = "user") -> str:
    """Show cluster utilisation report for a user.

    Args:
        user: Username to query.
    """
    return (
        "-----------------------------------------------------------\n"
        "Cluster/Account/User Utilization 2024-01-01 - 2024-01-31\n"
        "Usage reported in CPU Minutes\n"
        "-----------------------------------------------------------\n"
        "   Cluster         Account     Login       Used\n"
        "--------- --------------- --------- ----------\n"
        "dlcluster            root                12,400\n"
        f"dlcluster      {user:<12} {user:<10}  298,102\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fake Slurm MCP Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "9000")))
    parser.add_argument("--path", default=os.environ.get("MCP_PATH", "/mcp"))
    args = parser.parse_args()

    print(
        Fore.GREEN +
        f"[mcp-server] fake-slurm-cluster  →  "
        f"http://{args.host}:{args.port}{args.path}"
    )
    print(Fore.YELLOW + "[mcp-server] Reachable from sandbox via host's LAN/bridge IP on that port.")
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        path=args.path,
        show_banner=False,
    )
