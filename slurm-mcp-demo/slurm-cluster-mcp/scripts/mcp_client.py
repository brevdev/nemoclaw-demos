#!/usr/bin/env python3
"""
Direct MCP tool caller for the fake Slurm cluster.

The OpenClaw agent (which already has an LLM) decides which tool to call and
with what arguments. This script executes that one tool call against the remote
MCP server and prints the result to stdout. No secondary LLM is involved.

Usage:
  <skill_dir>/venv/bin/python3 mcp_client.py <tool> [options]

Tools:
  get_hostname
  sinfo
  srun        [--gpus N] [--time-limit HH:MM:SS] [--epochs N] [--model NAME]
  sbatch      [--script-name NAME]
  squeue      [--user NAME]
  sacctmgr    [--user NAME]
  sreport     [--user NAME]

Server URL (resolved in order):
  1. --server-url flag
  2. MCP_SERVER_URL env var
  3. Default: http://host.openshell.internal:9000/mcp

Always run with the skill venv's Python so the sandbox policy allows the
outbound connection to port 9000. Do NOT use bare python3.
"""
from __future__ import annotations

import asyncio
import os
import sys
import argparse

try:
    from fastmcp import Client
except ImportError as _e:
    _skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _venv_python = os.path.join(_skill_dir, "venv", "bin", "python3")
    print(
        f"\nMissing dependency: {_e}\n"
        "Run this script with the skill venv's Python, not bare python3:\n\n"
        f"  {_venv_python} {__file__} <tool> [args]\n\n"
        "If the venv doesn't exist yet, create it with:\n\n"
        f"  python3 -m venv {_skill_dir}/venv\n"
        f"  {_skill_dir}/venv/bin/pip install -q fastmcp\n",
        file=sys.stderr,
    )
    sys.exit(1)

_DEFAULT_URL = "http://host.openshell.internal:9000/mcp"


async def call_tool(server_url: str, tool: str, args: dict) -> str:
    async with Client(server_url) as client:
        result = await client.call_tool(tool, args)
    return result.content[0].text


def main() -> None:
    root = argparse.ArgumentParser(
        description="Call a specific Slurm MCP tool directly.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    root.add_argument(
        "--server-url",
        default=os.environ.get("MCP_SERVER_URL", _DEFAULT_URL),
        help="Full URL of the MCP server.",
    )

    sub = root.add_subparsers(dest="tool", metavar="<tool>", required=True)

    sub.add_parser("get_hostname", help="Return the cluster headnode hostname.")
    sub.add_parser("sinfo", help="Show available partitions and node states.")

    p_srun = sub.add_parser("srun", help="Launch a fake interactive training job.")
    p_srun.add_argument("--gpus", type=int, default=1, help="Number of GPUs to allocate.")
    p_srun.add_argument("--time-limit", default="01:00:00", help="Wall-time limit HH:MM:SS.")
    p_srun.add_argument("--epochs", type=int, default=5, help="Training epochs to simulate.")
    p_srun.add_argument("--model", default="resnet50", help="Model name for the epoch log.")

    p_sbatch = sub.add_parser("sbatch", help="Submit a fake batch job.")
    p_sbatch.add_argument("--script-name", default="train.sh", help="Batch script filename.")

    p_squeue = sub.add_parser("squeue", help="Show the Slurm job queue.")
    p_squeue.add_argument("--user", default="user", help='Username to filter; "all" for everyone.')

    p_sacctmgr = sub.add_parser("sacctmgr", help="Show account associations for a user.")
    p_sacctmgr.add_argument("--user", default="user", help="Username to query.")

    p_sreport = sub.add_parser("sreport", help="Show cluster utilisation report.")
    p_sreport.add_argument("--user", default="user", help="Username to query.")

    parsed = root.parse_args()
    server_url = parsed.server_url
    tool = parsed.tool

    # Build the args dict for the tool call (strip server_url and tool keys)
    tool_args: dict = {}
    if tool == "srun":
        tool_args = {
            "gpus": parsed.gpus,
            "time_limit": parsed.time_limit,
            "epochs": parsed.epochs,
            "model": parsed.model,
        }
    elif tool == "sbatch":
        tool_args = {"script_name": parsed.script_name}
    elif tool in ("squeue", "sacctmgr", "sreport"):
        tool_args = {"user": parsed.user}

    try:
        result = asyncio.run(call_tool(server_url, tool, tool_args))
        print(result)
    except Exception as exc:
        print(f"Error calling '{tool}': {exc}", file=sys.stderr)
        print(f"Is the server reachable at {server_url}?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
