#!/usr/bin/env python3
"""
Direct MCP tool caller for the Outlook PST server.

The OpenClaw agent (which already has an LLM) decides which tool to call and
with what arguments. This script executes that one tool call against the remote
MCP server and prints the result to stdout. No secondary LLM is involved.

Usage:
  <skill_dir>/venv/bin/python3 pst_client.py <tool> [options]

Tools:
  extract_pst              [--pst-path PATH] [--max-emails N] [--max-contacts N]
  search_emails_by_sender  --sender ADDR [--pst-path PATH] [--max-results N] [--folder NAME]
  get_latest_emails        [--count N] [--pst-path PATH] [--folder NAME]
  list_pst_folders         [--pst-path PATH]
  search_emails_by_subject --keyword TEXT [--pst-path PATH] [--max-results N]
  get_emails_by_date_range --start-date DATE --end-date DATE [--pst-path PATH] [--max-results N] [--folder NAME]
  count_emails             [--pst-path PATH]
  draft_email              --out-path PATH|--append-to-pst PATH [options]

Server URL (resolved in order):
  1. --server-url flag
  2. MCP_SERVER_URL env var
  3. Default: http://host.openshell.internal:9003/mcp

Always run with the skill venv's Python so the sandbox policy allows the
outbound connection to port 9003. Do NOT use bare python3.
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

_DEFAULT_URL = "http://host.openshell.internal:9003/mcp"


async def call_tool(server_url: str, tool: str, args: dict) -> str:
    async with Client(server_url) as client:
        result = await client.call_tool(tool, args)
    return result.content[0].text


def main() -> None:
    root = argparse.ArgumentParser(
        description="Call a specific PST MCP tool directly.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    root.add_argument(
        "--server-url",
        default=os.environ.get("MCP_SERVER_URL", _DEFAULT_URL),
        help="Full URL of the MCP server.",
    )

    sub = root.add_subparsers(dest="tool", metavar="<tool>", required=True)

    # extract_pst
    p_extract = sub.add_parser("extract_pst", help="Full extract of all emails and contacts.")
    p_extract.add_argument("--pst-path", default="", help="Absolute path to the .pst file.")
    p_extract.add_argument("--max-emails", type=int, default=None, help="Stop after this many emails.")
    p_extract.add_argument("--max-contacts", type=int, default=None, help="Stop after this many contacts.")

    # search_emails_by_sender
    p_sender = sub.add_parser("search_emails_by_sender", help="Find emails from a specific sender.")
    p_sender.add_argument("--sender", required=True, help="Email address or name fragment to search for.")
    p_sender.add_argument("--pst-path", default="", help="Absolute path to the .pst file.")
    p_sender.add_argument("--max-results", type=int, default=50, help="Maximum number of results.")
    p_sender.add_argument("--folder", default=None, dest="folder_name", help="Search only this folder.")

    # get_latest_emails
    p_latest = sub.add_parser("get_latest_emails", help="Get the N most recent emails.")
    p_latest.add_argument("--count", type=int, default=10, help="Number of recent emails to return.")
    p_latest.add_argument("--pst-path", default="", help="Absolute path to the .pst file.")
    p_latest.add_argument("--folder", default=None, dest="folder_name", help="Limit to this folder.")

    # list_pst_folders
    p_folders = sub.add_parser("list_pst_folders", help="Show folder tree with item counts.")
    p_folders.add_argument("--pst-path", default="", help="Absolute path to the .pst file.")

    # search_emails_by_subject
    p_subject = sub.add_parser("search_emails_by_subject", help="Find emails by subject keyword.")
    p_subject.add_argument("--keyword", required=True, help="Word or phrase to search for in the subject.")
    p_subject.add_argument("--pst-path", default="", help="Absolute path to the .pst file.")
    p_subject.add_argument("--max-results", type=int, default=50, help="Maximum number of results.")

    # get_emails_by_date_range
    p_date = sub.add_parser("get_emails_by_date_range", help="Find emails within a delivery-date range.")
    p_date.add_argument("--start-date", required=True, help="Start date (inclusive), ISO-8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    p_date.add_argument("--end-date", required=True, help="End date (inclusive), ISO-8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")
    p_date.add_argument("--pst-path", default="", help="Absolute path to the .pst file.")
    p_date.add_argument("--max-results", type=int, default=100, help="Maximum number of results.")
    p_date.add_argument("--folder", default=None, dest="folder_name", help="Search only this folder.")

    # count_emails
    p_count = sub.add_parser("count_emails", help="Count email items per folder plus grand total.")
    p_count.add_argument("--pst-path", default="", help="Absolute path to the .pst file.")

    # draft_email
    p_draft = sub.add_parser("draft_email", help="Create an unsent draft email (MSG/EML).")
    p_draft.add_argument("--subject", default="", help="Message subject.")
    p_draft.add_argument("--body", default="", help="Plain-text body (ignored if --body-file is set).")
    p_draft.add_argument("--to-addresses", default="", help="Comma-separated To addresses.")
    p_draft.add_argument("--cc-addresses", default="", help="Comma-separated Cc addresses.")
    p_draft.add_argument("--bcc-addresses", default="", help="Comma-separated Bcc addresses.")
    p_draft.add_argument("--from-address", default=None, help="Optional From address.")
    p_draft.add_argument("--body-file", default=None, help="Path to a UTF-8 file to use as body.")
    p_draft.add_argument("--out-path", default=None, help="Save draft to this file path (.msg or .eml).")
    p_draft.add_argument("--file-format", default="msg", choices=["msg", "eml"], help="Output format.")
    p_draft.add_argument("--append-to-pst", default=None, help="Also append draft to this PST's Drafts folder.")

    parsed = root.parse_args()
    server_url = parsed.server_url
    tool = parsed.tool

    # Build args dict for the tool call
    tool_args: dict = {}

    if tool == "extract_pst":
        tool_args = {"pst_path": parsed.pst_path}
        if parsed.max_emails is not None:
            tool_args["max_emails"] = parsed.max_emails
        if parsed.max_contacts is not None:
            tool_args["max_contacts"] = parsed.max_contacts

    elif tool == "search_emails_by_sender":
        tool_args = {
            "sender": parsed.sender,
            "pst_path": parsed.pst_path,
            "max_results": parsed.max_results,
        }
        if parsed.folder_name:
            tool_args["folder_name"] = parsed.folder_name

    elif tool == "get_latest_emails":
        tool_args = {
            "count": parsed.count,
            "pst_path": parsed.pst_path,
        }
        if parsed.folder_name:
            tool_args["folder_name"] = parsed.folder_name

    elif tool == "list_pst_folders":
        tool_args = {"pst_path": parsed.pst_path}

    elif tool == "search_emails_by_subject":
        tool_args = {
            "keyword": parsed.keyword,
            "pst_path": parsed.pst_path,
            "max_results": parsed.max_results,
        }

    elif tool == "get_emails_by_date_range":
        tool_args = {
            "start_date": parsed.start_date,
            "end_date": parsed.end_date,
            "pst_path": parsed.pst_path,
            "max_results": parsed.max_results,
        }
        if parsed.folder_name:
            tool_args["folder_name"] = parsed.folder_name

    elif tool == "count_emails":
        tool_args = {"pst_path": parsed.pst_path}

    elif tool == "draft_email":
        tool_args = {
            "subject": parsed.subject,
            "body": parsed.body,
            "to_addresses": parsed.to_addresses,
            "cc_addresses": parsed.cc_addresses,
            "bcc_addresses": parsed.bcc_addresses,
            "file_format": parsed.file_format,
        }
        if parsed.from_address:
            tool_args["from_address"] = parsed.from_address
        if parsed.body_file:
            tool_args["body_file"] = parsed.body_file
        if parsed.out_path:
            tool_args["out_path"] = parsed.out_path
        if parsed.append_to_pst:
            tool_args["append_to_pst"] = parsed.append_to_pst

    try:
        result = asyncio.run(call_tool(server_url, tool, tool_args))
        print(result)
    except Exception as exc:
        print(f"Error calling '{tool}': {exc}", file=sys.stderr)
        print(f"Is the server reachable at {server_url}?", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
