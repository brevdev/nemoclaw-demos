#!/usr/bin/env python3
"""
MCP client for the fake Slurm cluster — natural-language REPL.

Designed to run inside an OpenShell sandbox (or any machine separate from
the host running fake_cluster_mcp_server.py).

The server URL is resolved in this order:
  1. --server-url CLI flag
  2. MCP_SERVER_URL environment variable
  3. Default: http://host.docker.internal:9000/mcp
     (Docker's built-in alias for the host machine; works in most container runtimes)

Usage (inside the sandbox):
    # Export the host's address, then run:
    export MCP_SERVER_URL="http://<host-ip>:9000/mcp"
    python access_cluster_mcp_client.py

    # Or pass directly:
    python access_cluster_mcp_client.py --server-url http://192.168.1.10:9000/mcp

Example queries:
    "what GPU partitions are available?"
    "launch a training job with 4 GPUs for 10 epochs using vit-large"
    "submit my train_bert.sh as a batch job"
    "show me what jobs are running"
    "what are my account limits?"
    "how much compute have I used this month?"
"""
import asyncio
import os
import argparse

from colorama import Fore, init as colorama_init
from dotenv import load_dotenv
from fastmcp import Client

load_dotenv()
colorama_init(autoreset=True)

# ---------------------------------------------------------------------------
# Configuration — resolved at startup, printed so the user can verify
# ---------------------------------------------------------------------------
_DEFAULT_URL = "http://host.docker.internal:9000/mcp"


def _resolve_server_url(cli_arg: str | None) -> str:
    if cli_arg:
        return cli_arg
    return os.environ.get("MCP_SERVER_URL", _DEFAULT_URL)


# ---------------------------------------------------------------------------
# MCP call
# ---------------------------------------------------------------------------

async def ask_cluster(server_url: str, query: str) -> str:
    """Send a natural-language query to the cluster_agent tool on the server."""
    async with Client(server_url) as client:
        result = await client.call_tool("cluster_agent", {"query": query})
    return result.content[0].text


def stream_print(text: str):
    """Print word-by-word with green color to simulate streaming output."""
    words = text.split(" ")
    for i, word in enumerate(words):
        print(
            Fore.GREEN + word,
            end="" if i == len(words) - 1 else " ",
            flush=True,
        )
    print()


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def repl(server_url: str):
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "  Fake Slurm Cluster — natural language interface")
    print(Fore.CYAN + f"  Server : {server_url}")
    print(Fore.CYAN + "  Type 'quit' or Ctrl-C to exit.")
    print(Fore.CYAN + "=" * 60 + "\n")

    while True:
        try:
            query = input(Fore.YELLOW + "cluster> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not query:
            continue
        if query.lower() in ("quit", "exit", "q"):
            break

        try:
            result = asyncio.run(ask_cluster(server_url, query))
        except Exception as exc:
            print(Fore.RED + f"Error: {exc}")
            print(Fore.RED + f"Is the server reachable at {server_url}?")
            continue

        print()
        stream_print(result)
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fake Slurm MCP Client (sandbox-side)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--server-url",
        default="http://host.openshell.internal:9000/mcp",
        help=(
            "Full URL of the MCP server, e.g. http://192.168.1.10:9000/mcp. "
            "Overrides MCP_SERVER_URL env var."
        ),
    )
    args = parser.parse_args()

    server_url = _resolve_server_url(args.server_url)
    repl(server_url)
