#!/usr/bin/env python3
"""
Fake Slurm HPC headnode — MCP server with LLM-powered natural-language dispatcher.

Tools exposed:
  cluster_agent  — natural-language dispatcher (LLM picks the right tool)
  get_hostname   — return headnode hostname
  sinfo          — show partitions / node states
  srun           — launch a fake interactive training job
  sbatch         — submit a fake batch job
  squeue         — show job queue
  sacctmgr       — show account associations
  sreport        — show utilisation report

Environment:
  NVIDIA_API_KEY  — required for the LLM dispatcher (ChatNVIDIA)

Run:
  python fake_cluster_mcp_server.py              # streamable-http on 127.0.0.1:9000/mcp
  python fake_cluster_mcp_server.py --port 9000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re

from colorama import Fore, init as colorama_init
from dotenv import load_dotenv
from fastmcp import FastMCP
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_nvidia_ai_endpoints import ChatNVIDIA

load_dotenv()
colorama_init(autoreset=True)

mcp = FastMCP("fake-slurm-cluster")

# ---------------------------------------------------------------------------
# LLM client  (requires NVIDIA_API_KEY in env or .env)
# ---------------------------------------------------------------------------
_llm = ChatNVIDIA(
    model="meta/llama-3.3-70b-instruct",
    api_key=os.environ.get("NVIDIA_API_KEY", ""),
)

# ---------------------------------------------------------------------------
# In-memory job table (persists for the lifetime of the server process)
# ---------------------------------------------------------------------------
_jobs: dict[int, dict] = {}
_next_job_id = 42001

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _parse_intent(natural_language: str) -> dict:
    """Ask the LLM to convert a NL query into {tool, args} JSON."""
    system_prompt = """\
You are a parameter-extraction assistant for an HPC cluster scheduler (Slurm).
Given a natural-language request return ONLY a valid JSON object — no markdown,
no explanation, no extra text.

The JSON must have exactly two keys:
  "tool"  — one of the tool names listed below
  "args"  — an object with the parameters for that tool (empty object {} if none)

TOOLS AND THEIR PARAMETERS
───────────────────────────

"get_hostname"
  (no args)
  → Use when: user asks for the cluster name or headnode hostname.

"sinfo"
  (no args)
  → Use when: user asks about partitions, nodes, GPU types, available compute.
    e.g. "what GPUs are available?", "show me the partitions", "what nodes are idle?"

"srun"
  gpus       (integer, default 1)           — number of GPUs to allocate
  time_limit (string,  default "01:00:00")  — wall-time limit HH:MM:SS
  epochs     (integer, default 5)           — training epochs to simulate
  model      (string,  default "resnet50")  — model architecture name
  → Use when: user wants to launch / run / start a training job interactively.
    e.g. "run a training job with 4 GPUs for 10 epochs using vit-large"

"sbatch"
  script_name (string, default "train.sh")  — name of the batch script
  → Use when: user wants to submit a batch job.
    e.g. "submit train_bert.sh as a batch job"

"squeue"
  user (string, default "user")  — username to filter; use "all" for everyone
  → Use when: user asks about running jobs, queue status.
    e.g. "what jobs are running?", "show the queue"

"sacctmgr"
  user (string, default "user")  — username to query
  → Use when: user asks about compute allocation, account limits, associations.
    e.g. "what compute am I allowed to use?", "show my account limits"

"sreport"
  user (string, default "user")  — username to query
  → Use when: user asks about utilisation, usage history, compute consumption.
    e.g. "how much compute have I used?", "show usage report"

Rules:
- Return ONLY the JSON object.
- Omit optional keys when not mentioned — use the defaults listed above.
- If the request is ambiguous, choose the most likely tool.
"""
    response = _llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=natural_language),
    ])
    raw = _strip_think(response.content.strip())
    print(Fore.YELLOW + f"[cluster_agent] LLM raw → {raw}")
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"LLM did not return valid JSON: {raw!r}")
    return json.loads(match.group())


# ---------------------------------------------------------------------------
# Individual tool implementations
# ---------------------------------------------------------------------------

def _do_get_hostname() -> str:
    return "dlcluster-headnode"


def _do_sinfo() -> str:
    return (
        "PARTITION    AVAIL  TIMELIMIT   NODES  STATE  NODELIST\n"
        "gpu-a100*    up     infinite        4  idle   node[01-04]\n"
        "gpu-h100     up     2-00:00:00      8  idle   node[05-12]\n"
        "gpu-gb200    up     4-00:00:00      2  idle   node[13-14]\n"
        "cpu-general  up     infinite       16  idle   node[15-30]\n"
    )


def _do_srun(gpus: int = 1, time_limit: str = "01:00:00",
             epochs: int = 5, model: str = "resnet50") -> str:
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


def _do_sbatch(script_name: str = "train.sh") -> str:
    global _next_job_id
    job_id = _next_job_id
    _next_job_id += 1
    _jobs[job_id] = {"state": "RUNNING", "user": "user",
                     "partition": "gpu-a100", "name": script_name}
    return f"Submitted batch job {job_id}"


def _do_squeue(user: str = "user") -> str:
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


def _do_sacctmgr(user: str = "user") -> str:
    return (
        "   Cluster    Account       User  Partition  Share  MaxJobs        QOS\n"
        "---------- ---------- --------- ---------- ------  -------  ---------\n"
        "dlcluster        root                            1             normal\n"
        "dlcluster        root      root                  1             normal\n"
        f"dlcluster     {user:<10}                    1             normal\n"
        f"dlcluster     {user:<10} {user:<9}            1      200    normal\n"
    )


def _do_sreport(user: str = "user") -> str:
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
# MCP tools
# ---------------------------------------------------------------------------

_DISPATCH = {
    "get_hostname": lambda args: _do_get_hostname(),
    "sinfo":        lambda args: _do_sinfo(),
    "srun":         lambda args: _do_srun(**args),
    "sbatch":       lambda args: _do_sbatch(**args),
    "squeue":       lambda args: _do_squeue(**args),
    "sacctmgr":     lambda args: _do_sacctmgr(**args),
    "sreport":      lambda args: _do_sreport(**args),
}


@mcp.tool()
def cluster_agent(query: str) -> str:
    """Natural-language interface to all fake Slurm cluster operations.

    Accepts a plain-English request, uses an LLM to identify the intent and
    extract parameters, then dispatches to the correct tool automatically.

    Args:
        query: e.g. "show me all idle GPU nodes"
               "launch a training job with 8 H100s for 20 epochs using vit-large"
               "how much compute have I used this month?"
               "submit my train_bert.sh batch script"
               "what jobs are currently running?"
    """
    try:
        parsed = _parse_intent(query)
    except Exception as ex:
        return f"[cluster_agent] intent-parse error: {type(ex).__name__}: {ex}"

    tool_name = parsed.get("tool", "")
    args      = parsed.get("args", {})
    print(Fore.CYAN + f"[cluster_agent] tool={tool_name!r}  args={args}")

    handler = _DISPATCH.get(tool_name)
    if handler is None:
        valid = ", ".join(_DISPATCH)
        return (
            f"[cluster_agent] unknown tool '{tool_name}'. "
            f"Valid tools: {valid}"
        )

    try:
        return handler(args)
    except Exception as ex:
        return f"[cluster_agent] {tool_name} error: {type(ex).__name__}: {ex}"


@mcp.tool()
def get_hostname() -> str:
    """Return the cluster headnode hostname."""
    return _do_get_hostname()


@mcp.tool()
def sinfo() -> str:
    """Show available Slurm partitions and node states."""
    return _do_sinfo()


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
    return _do_srun(gpus, time_limit, epochs, model)


@mcp.tool()
def sbatch(script_name: str = "train.sh") -> str:
    """Submit a fake batch job.

    Args:
        script_name: Name of the batch script.
    """
    return _do_sbatch(script_name)


@mcp.tool()
def squeue(user: str = "user") -> str:
    """Show jobs in the Slurm queue.

    Args:
        user: Filter by username; "all" to see every job.
    """
    return _do_squeue(user)


@mcp.tool()
def sacctmgr(user: str = "user") -> str:
    """Show Slurm account associations for a user.

    Args:
        user: Username to query.
    """
    return _do_sacctmgr(user)


@mcp.tool()
def sreport(user: str = "user") -> str:
    """Show cluster utilisation report for a user.

    Args:
        user: Username to query.
    """
    return _do_sreport(user)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fake Slurm MCP Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Default to 0.0.0.0 so the server is reachable from sandboxes / containers
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
