#!/usr/bin/env python3
"""
Direct MCP tool caller for the ALFWorld Visual Environment server.

The OpenClaw agent (which already has an LLM with tool-calling capability)
decides which tool to invoke and with what arguments.  This script executes
that one tool call against the remote MCP server and prints the result to
stdout.  No secondary LLM or game-loop logic runs here.

Usage:
  <skill_dir>/venv/bin/python3 sandbox_client_vis.py <tool> [options]

Tools:
  reset_env
  step_env                 --action ACTION
  get_admissible_commands
  get_current_state
  get_current_frame_info
  upload_frame_to_sandbox  --sandbox-name NAME [--step N]
  get_game_log             [--last-n N]
  search_game_log          --pattern PATTERN

Server URL (resolved in order):
  1. --server-url flag
  2. MCP_SERVER_URL env var
  3. Default: http://host.openshell.internal:9001/mcp

Always run with the skill venv's Python so the sandbox policy allows the
outbound connection to port 9001.  Do NOT use bare python3.
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

_DEFAULT_URL = "http://host.openshell.internal:9001/mcp"


async def call_tool(server_url: str, tool: str, args: dict) -> str:
    async with Client(server_url) as client:
        result = await client.call_tool(tool, args)
    return result.content[0].text


def main() -> None:
    root = argparse.ArgumentParser(
        description="Call a specific ALFWorld Visual MCP tool directly.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    root.add_argument(
        "--server-url",
        default=os.environ.get("MCP_SERVER_URL", _DEFAULT_URL),
        help="Full URL of the MCP server.",
    )

    sub = root.add_subparsers(dest="tool", metavar="<tool>", required=True)

    # reset_env
    sub.add_parser("reset_env",
                   help="Reset the ALFWorld THOR environment and start a new episode.")

    # step_env
    p_step = sub.add_parser("step_env",
                             help="Execute an action in the THOR environment.")
    p_step.add_argument("--action", required=True,
                        help="One of the currently admissible action strings.")

    # get_admissible_commands
    sub.add_parser("get_admissible_commands",
                   help="Return the list of currently valid action strings.")

    # get_current_state
    sub.add_parser("get_current_state",
                   help="Return a full snapshot of the current game state (text + frame).")

    # get_current_frame_info
    sub.add_parser("get_current_frame_info",
                   help="Return metadata about the most recently saved visual frame.")

    # upload_frame_to_sandbox
    p_upload = sub.add_parser("upload_frame_to_sandbox",
                               help="Upload a saved frame PNG to a sandbox via openshell.")
    p_upload.add_argument("--sandbox-name", required=True,
                          help="Name of the target sandbox (e.g. 'my-sandbox').")
    p_upload.add_argument("--step", type=int, default=None,
                          help="Step number to upload (defaults to latest step).")

    # get_game_log
    p_log = sub.add_parser("get_game_log",
                            help="Return the last N step blocks from game_log_visual.md.")
    p_log.add_argument("--last-n", type=int, default=10,
                       help="Number of recent steps to return.")

    # search_game_log
    p_search = sub.add_parser("search_game_log",
                               help="Search game_log_visual.md for lines matching a pattern.")
    p_search.add_argument("--pattern", required=True,
                          help="Plain text or regex pattern to search for.")

    parsed = root.parse_args()
    server_url = parsed.server_url
    tool = parsed.tool

    # Build args dict for the tool call
    tool_args: dict = {}

    if tool == "reset_env":
        tool_args = {}

    elif tool == "step_env":
        tool_args = {"action": parsed.action}

    elif tool == "get_admissible_commands":
        tool_args = {}

    elif tool == "get_current_state":
        tool_args = {}

    elif tool == "get_current_frame_info":
        tool_args = {}

    elif tool == "upload_frame_to_sandbox":
        tool_args = {"sandbox_name": parsed.sandbox_name}
        if parsed.step is not None:
            tool_args["step"] = parsed.step

    elif tool == "get_game_log":
        tool_args = {"last_n": parsed.last_n}

    elif tool == "search_game_log":
        tool_args = {"pattern": parsed.pattern}

    try:
        result = asyncio.run(call_tool(server_url, tool, tool_args))
        print(result)
    except Exception as exc:
        print(f"Error calling '{tool}': {exc}", file=sys.stderr)
        print(f"Is the server reachable at {server_url}?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
