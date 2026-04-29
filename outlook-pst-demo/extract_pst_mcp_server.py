#!/usr/bin/env python3
"""
Outlook PST MCP server — direct tool access to PST operations.

The OpenClaw agent (which has its own LLM) decides which tool to call.
No secondary LLM or NL dispatcher runs here.

Tools exposed:
  extract_pst              — full extract of all emails + contacts
  search_emails_by_sender  — find all emails from a given sender address/name
  get_latest_emails        — retrieve the N most recent emails (sorted by date)
  list_pst_folders         — show folder tree with item counts
  search_emails_by_subject — find emails whose subject contains a keyword
  get_emails_by_date_range — find emails within a delivery-date range
  count_emails             — count email items per folder + grand total
  draft_email              — compose an unsent draft MSG/EML

Depends on:
  pip install fastmcp colorama python-dotenv
  plus Aspose.Email-for-Python-via-NET

Run:
  python extract_pst_mcp_server.py
  python extract_pst_mcp_server.py --port 9003

Default URL: http://0.0.0.0:9003/mcp

Environment:
  ASPOSE_EMAIL_LICENSE_PATH  — optional .lic file
  PST_PATH                   — default PST file path (overrides built-in sample)
  MCP_EXTRACT_PST_HOST       — bind host  (default 0.0.0.0)
  MCP_EXTRACT_PST_PORT       — bind port  (default 9003)
  MCP_EXTRACT_PST_PATH       — URL path   (default /mcp)
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

_EXAMPLES = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from colorama import Fore, init as colorama_init
from fastmcp import FastMCP

colorama_init(autoreset=True)

_DEFAULT_PST = str(_EXAMPLES / "data" / "Outlook.pst")
DEFAULT_PST = os.environ.get("PST_PATH") or _DEFAULT_PST

mcp = FastMCP("ExtractPstMCP")


# ---------------------------------------------------------------------------
# Aspose helpers (inlined — no separate pst_lib module needed)
# ---------------------------------------------------------------------------

def _apply_license(lic_path: Optional[str]) -> None:
    """Apply an Aspose.Email license file if one is provided."""
    if lic_path:
        try:
            from aspose.email import License
            lic = License()
            lic.set_license(lic_path)
        except Exception:
            pass


def _is_likely_mail(mapi) -> bool:
    """Return True if the MAPI item is an email (not a contact, calendar, etc.)."""
    msg_class = _safe(getattr(mapi, "message_class", "")).upper()
    return not msg_class or msg_class.startswith("IPM.NOTE")


def run_extract_to_string(
    pst_path: str,
    max_emails: Optional[int],
    max_contacts: Optional[int],
) -> str:
    """Walk the PST and return all emails and contacts as a formatted string."""
    from aspose.email.storage.pst import PersonalStorage

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))
    buf = io.StringIO()
    email_count = 0
    contact_count = 0

    def _walk(folder, store):
        nonlocal email_count, contact_count
        try:
            messages = folder.get_contents()
        except Exception:
            return
        for info in messages:
            try:
                mapi = store.extract_message(info)
            except Exception as ex:
                buf.write(f"[skip] {ex}\n")
                continue
            msg_class = _safe(getattr(mapi, "message_class", "")).upper()
            if msg_class.startswith("IPM.CONTACT"):
                if max_contacts and contact_count >= max_contacts:
                    continue
                contact_count += 1
                buf.write(f"--- Contact #{contact_count} ---\n")
                buf.write(f"Name : {_safe(mapi.subject)}\n\n")
            elif not msg_class or msg_class.startswith("IPM.NOTE"):
                if max_emails and email_count >= max_emails:
                    continue
                email_count += 1
                buf.write(_format_message(mapi, email_count, _safe(folder.display_name)))
        if folder.has_sub_folders:
            for sub in folder.get_sub_folders():
                _walk(sub, store)

    with PersonalStorage.from_file(pst_path, False) as store:
        _walk(store.root_folder, store)

    return (
        f"Extracted {email_count} email(s) and {contact_count} contact(s).\n\n"
        + buf.getvalue()
    )


def run_draft_to_string(
    subject: str,
    body: str,
    body_file: Optional[str],
    to_addresses: str,
    cc_addresses: Optional[str],
    bcc_addresses: Optional[str],
    from_address: Optional[str],
    out_path: Optional[str],
    file_format: str,
    append_to_pst: Optional[str],
) -> str:
    """Create an unsent draft email and save it as MSG/EML and/or append to PST."""
    from aspose.email.mapi import MapiMessage, MapiRecipientType

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))

    if body_file:
        with open(body_file, encoding="utf-8") as fh:
            body = fh.read()

    msg = MapiMessage()
    msg.subject = subject or ""
    msg.body = body or ""
    if from_address:
        msg.sender_email_address = from_address

    for addr in (to_addresses or "").split(","):
        addr = addr.strip()
        if addr:
            msg.recipients.add(addr, addr, MapiRecipientType.MAPI_TO)
    for addr in (cc_addresses or "").split(","):
        addr = addr.strip()
        if addr:
            msg.recipients.add(addr, addr, MapiRecipientType.MAPI_CC)
    for addr in (bcc_addresses or "").split(","):
        addr = addr.strip()
        if addr:
            msg.recipients.add(addr, addr, MapiRecipientType.MAPI_BCC)

    lines = []

    if out_path:
        dest = Path(out_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if file_format == "eml":
            from aspose.email import SaveOptions
            from aspose.email.mapi import MapiConversionOptions
            mail = msg.to_mail_message(MapiConversionOptions.unicode_format)
            mail.save(str(dest), SaveOptions.default_eml)
        else:
            msg.save(str(dest))
        lines.append(f"Draft saved to {out_path}")

    if append_to_pst:
        from aspose.email.storage.pst import PersonalStorage, StandardIpmFolder
        with PersonalStorage.from_file(append_to_pst) as pst:
            drafts = pst.get_predefined_folder(StandardIpmFolder.DRAFTS)
            if drafts is None:
                drafts = pst.create_predefined_folder("Drafts", StandardIpmFolder.DRAFTS)
            drafts.add_message(msg)
        lines.append(f"Draft appended to PST Drafts folder: {append_to_pst}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe(v) -> str:
    return "" if v is None else str(v)


def _truncate(text: str, n: int = 400) -> str:
    text = text.replace("\r\n", "\n").strip()
    return text if len(text) <= n else text[: n - 3] + "..."


def _format_message(mapi, idx: int, folder_name: str) -> str:
    lines = [
        f"--- Email #{idx} | folder: {folder_name} ---",
        f"Subject : {_safe(mapi.subject)}",
        f"From    : {_safe(mapi.sender_name)} <{_safe(mapi.sender_email_address)}>",
        f"To      : {_safe(mapi.display_to)}",
    ]
    if _safe(mapi.display_cc):
        lines.append(f"Cc      : {_safe(mapi.display_cc)}")
    lines.append(f"Date    : {_safe(mapi.delivery_time)}")
    body = _safe(mapi.body)
    if body:
        lines.append(f"Body    :\n{_truncate(body)}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PST query functions (sync — called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _search_by_sender_sync(
    pst_path: str,
    sender: str,
    max_results: int,
    folder_name: Optional[str],
) -> str:
    from aspose.email.storage.pst import PersonalStorage, PersonalStorageQueryBuilder

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))
    buf = io.StringIO()

    with PersonalStorage.from_file(pst_path, False) as store:
        if folder_name:
            folders = [store.root_folder.get_sub_folder(folder_name)]
            if folders[0] is None:
                return f"Folder '{folder_name}' not found in PST."
        else:
            folders = list(store.root_folder.get_sub_folders())
            folders.insert(0, store.root_folder)

        qb = PersonalStorageQueryBuilder()
        qb.from_address.contains(sender, True)
        query = qb.get_query()

        found = 0
        for folder in folders:
            if max_results and found >= max_results:
                break
            try:
                messages = folder.get_contents(query)
            except Exception:
                messages = []
            for info in messages:
                if max_results and found >= max_results:
                    break
                try:
                    mapi = store.extract_message(info)
                except Exception as ex:
                    buf.write(f"[skip] {ex}\n")
                    continue
                if not _is_likely_mail(mapi):
                    continue
                found += 1
                buf.write(_format_message(mapi, found, _safe(folder.display_name)))

            if not folder_name and folder.has_sub_folders:
                for sub in folder.get_sub_folders():
                    if max_results and found >= max_results:
                        break
                    try:
                        sub_msgs = sub.get_contents(query)
                    except Exception:
                        sub_msgs = []
                    for info in sub_msgs:
                        if max_results and found >= max_results:
                            break
                        try:
                            mapi = store.extract_message(info)
                        except Exception as ex:
                            buf.write(f"[skip] {ex}\n")
                            continue
                        if not _is_likely_mail(mapi):
                            continue
                        found += 1
                        buf.write(_format_message(mapi, found, _safe(sub.display_name)))

    if found == 0:
        return f"No emails found from sender matching '{sender}'."
    header = f"Found {found} email(s) from '{sender}'"
    if max_results and found >= max_results:
        header += f" (stopped at limit {max_results})"
    return header + "\n\n" + buf.getvalue()


def _get_latest_emails_sync(
    pst_path: str,
    count: int,
    folder_name: Optional[str],
) -> str:
    from aspose.email.storage.pst import PersonalStorage

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))
    collected: List[Tuple] = []

    def _walk(folder, store):
        try:
            messages = folder.get_contents()
        except Exception:
            return
        for info in messages:
            try:
                mapi = store.extract_message(info)
            except Exception:
                continue
            if not _is_likely_mail(mapi):
                continue
            dt = mapi.delivery_time
            collected.append((dt, mapi, _safe(folder.display_name)))
        if folder.has_sub_folders:
            for sub in folder.get_sub_folders():
                _walk(sub, store)

    with PersonalStorage.from_file(pst_path, False) as store:
        if folder_name:
            target = store.root_folder.get_sub_folder(folder_name)
            if target is None:
                return f"Folder '{folder_name}' not found in PST."
            _walk(target, store)
        else:
            _walk(store.root_folder, store)

    if not collected:
        return "No emails found in PST."

    collected.sort(key=lambda x: x[0] if x[0] is not None else "", reverse=True)
    top = collected[:count]

    buf = io.StringIO()
    buf.write(f"Latest {len(top)} email(s) (sorted by date desc):\n\n")
    for idx, (_, mapi, fname) in enumerate(top, 1):
        buf.write(_format_message(mapi, idx, fname))
    return buf.getvalue()


def _list_folders_sync(pst_path: str) -> str:
    from aspose.email.storage.pst import PersonalStorage

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))
    buf = io.StringIO()

    def _walk(folder, depth: int):
        indent = "  " * depth
        total = getattr(folder, "content_count", "?")
        unread = getattr(folder, "content_unread_count", "?")
        buf.write(f"{indent}[{_safe(folder.display_name)}]  total={total}  unread={unread}\n")
        if folder.has_sub_folders:
            for sub in folder.get_sub_folders():
                _walk(sub, depth + 1)

    with PersonalStorage.from_file(pst_path, False) as store:
        store_name = _safe(getattr(store.store, "display_name", "")) or pst_path
        buf.write(f"PST store: {store_name}\n\n")
        _walk(store.root_folder, 0)

    return buf.getvalue()


def _search_by_subject_sync(
    pst_path: str,
    keyword: str,
    max_results: int,
) -> str:
    from aspose.email.storage.pst import PersonalStorage, PersonalStorageQueryBuilder

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))
    buf = io.StringIO()

    qb = PersonalStorageQueryBuilder()
    qb.subject.contains(keyword, True)
    query = qb.get_query()

    found = 0

    def _walk(folder, store):
        nonlocal found
        if max_results and found >= max_results:
            return
        try:
            messages = folder.get_contents(query)
        except Exception:
            messages = []
        for info in messages:
            if max_results and found >= max_results:
                return
            try:
                mapi = store.extract_message(info)
            except Exception as ex:
                buf.write(f"[skip] {ex}\n")
                continue
            if not _is_likely_mail(mapi):
                continue
            found += 1
            buf.write(_format_message(mapi, found, _safe(folder.display_name)))
        if folder.has_sub_folders:
            for sub in folder.get_sub_folders():
                _walk(sub, store)

    with PersonalStorage.from_file(pst_path, False) as store:
        _walk(store.root_folder, store)

    if found == 0:
        return f"No emails found with subject containing '{keyword}'."
    header = f"Found {found} email(s) with subject containing '{keyword}'"
    if max_results and found >= max_results:
        header += f" (stopped at limit {max_results})"
    return header + "\n\n" + buf.getvalue()


def _search_by_date_range_sync(
    pst_path: str,
    start_date: str,
    end_date: str,
    max_results: int,
    folder_name: Optional[str],
) -> str:
    from aspose.email.storage.pst import PersonalStorage, PersonalStorageQueryBuilder

    def _parse(s: str, end_of_day: bool = False) -> datetime:
        s = s.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                if fmt == "%Y-%m-%d" and end_of_day:
                    dt = dt.replace(hour=23, minute=59, second=59)
                return dt
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date {s!r}. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")

    try:
        dt_start = _parse(start_date, end_of_day=False)
        dt_end   = _parse(end_date,   end_of_day=True)
    except ValueError as exc:
        return f"Error: {exc}"

    if dt_start > dt_end:
        return "Error: start_date must be earlier than or equal to end_date."

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))
    buf = io.StringIO()

    qb = PersonalStorageQueryBuilder()
    qb.delivery_time.since(dt_start)
    qb.delivery_time.before(dt_end)
    query = qb.get_query()

    found = 0

    def _walk(folder, store):
        nonlocal found
        if max_results and found >= max_results:
            return
        try:
            messages = folder.get_contents(query)
        except Exception:
            messages = []
        for info in messages:
            if max_results and found >= max_results:
                return
            try:
                mapi = store.extract_message(info)
            except Exception as ex:
                buf.write(f"[skip] {ex}\n")
                continue
            if not _is_likely_mail(mapi):
                continue
            found += 1
            buf.write(_format_message(mapi, found, _safe(folder.display_name)))
        if folder.has_sub_folders:
            for sub in folder.get_sub_folders():
                _walk(sub, store)

    with PersonalStorage.from_file(pst_path, False) as store:
        if folder_name:
            target = store.root_folder.get_sub_folder(folder_name)
            if target is None:
                return f"Folder '{folder_name}' not found in PST."
            _walk(target, store)
        else:
            _walk(store.root_folder, store)

    if found == 0:
        return f"No emails found between {start_date} and {end_date}."
    header = f"Found {found} email(s) between {start_date} and {end_date}"
    if max_results and found >= max_results:
        header += f" (stopped at limit {max_results})"
    return header + "\n\n" + buf.getvalue()


def _count_emails_sync(pst_path: str) -> str:
    from aspose.email.storage.pst import PersonalStorage

    _apply_license(os.environ.get("ASPOSE_EMAIL_LICENSE_PATH"))
    buf = io.StringIO()

    def _walk(folder, depth: int) -> int:
        indent = "  " * depth
        folder_count = 0
        try:
            messages = folder.get_contents()
        except Exception:
            messages = []
        for info in messages:
            try:
                _ = info
                folder_count += 1
            except Exception:
                continue
        sub_count = 0
        if folder.has_sub_folders:
            for sub in folder.get_sub_folders():
                sub_count += _walk(sub, depth + 1)
        total_here = folder_count + sub_count
        buf.write(
            f"{indent}[{_safe(folder.display_name)}]  "
            f"direct={folder_count}  subtree={total_here}\n"
        )
        return total_here

    with PersonalStorage.from_file(pst_path, False) as store:
        store_name = _safe(getattr(store.store, "display_name", "")) or pst_path
        buf.write(f"PST: {store_name}\n\n")

        root = store.root_folder
        try:
            root_msgs = list(root.get_contents())
        except Exception:
            root_msgs = []
        root_direct = len(root_msgs)

        sub_total = 0
        if root.has_sub_folders:
            for sub in root.get_sub_folders():
                sub_total += _walk(sub, 1)

        grand_total = root_direct + sub_total
        buf.write(f"\nGrand total emails: {grand_total}\n")

    return buf.getvalue()


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def extract_pst(
    pst_path: str = "",
    max_emails: Optional[int] = None,
    max_contacts: Optional[int] = None,
) -> str:
    """Full extract of all emails and contacts from an Outlook PST file.

    Args:
        pst_path: Absolute path to the .pst file (defaults to built-in sample).
        max_emails: Stop after this many emails.
        max_contacts: Stop after this many contacts.
    """
    try:
        return await asyncio.to_thread(
            run_extract_to_string,
            pst_path or DEFAULT_PST,
            max_emails,
            max_contacts,
        )
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def search_emails_by_sender(
    sender: str,
    pst_path: str = "",
    max_results: int = 50,
    folder_name: Optional[str] = None,
) -> str:
    """Find all emails sent by a specific address or name (case-insensitive).

    Args:
        sender: Email address or name fragment, e.g. "alice@example.com" or "alice".
        pst_path: Absolute path to the .pst file (defaults to built-in sample).
        max_results: Maximum number of matching emails to return (default 50).
        folder_name: Search only this folder name (e.g. "Inbox"). Omit to search all folders.
    """
    try:
        return await asyncio.to_thread(
            _search_by_sender_sync,
            pst_path or DEFAULT_PST,
            sender,
            max_results,
            folder_name,
        )
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def get_latest_emails(
    count: int = 10,
    pst_path: str = "",
    folder_name: Optional[str] = None,
) -> str:
    """Retrieve the N most recent emails, sorted by delivery date descending.

    Args:
        count: Number of recent emails to return (default 10).
        pst_path: Absolute path to the .pst file (defaults to built-in sample).
        folder_name: Limit search to this folder (e.g. "Inbox"). Omit for all folders.
    """
    try:
        return await asyncio.to_thread(
            _get_latest_emails_sync,
            pst_path or DEFAULT_PST,
            count,
            folder_name,
        )
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def list_pst_folders(pst_path: str = "") -> str:
    """List the complete folder tree of a PST with item counts per folder.

    Args:
        pst_path: Absolute path to the .pst file (defaults to built-in sample).
    """
    try:
        return await asyncio.to_thread(_list_folders_sync, pst_path or DEFAULT_PST)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def search_emails_by_subject(
    keyword: str,
    pst_path: str = "",
    max_results: int = 50,
) -> str:
    """Find emails whose subject line contains a keyword (case-insensitive).

    Args:
        keyword: Word or phrase to search for in the subject, e.g. "project kickoff".
        pst_path: Absolute path to the .pst file (defaults to built-in sample).
        max_results: Maximum number of matching emails to return (default 50).
    """
    try:
        return await asyncio.to_thread(
            _search_by_subject_sync,
            pst_path or DEFAULT_PST,
            keyword,
            max_results,
        )
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def get_emails_by_date_range(
    start_date: str,
    end_date: str,
    pst_path: str = "",
    max_results: int = 100,
    folder_name: Optional[str] = None,
) -> str:
    """Fetch emails whose delivery date falls within a specific date range.

    Args:
        start_date: Start of the date range (inclusive). ISO-8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.
        end_date:   End of the date range (inclusive). ISO-8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.
        pst_path:   Absolute path to the .pst file (defaults to built-in sample).
        max_results: Maximum number of matching emails to return (default 100).
        folder_name: Search only this folder (e.g. "Inbox"). Omit to search all folders.
    """
    try:
        return await asyncio.to_thread(
            _search_by_date_range_sync,
            pst_path or DEFAULT_PST,
            start_date,
            end_date,
            max_results,
            folder_name,
        )
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def count_emails(pst_path: str = "") -> str:
    """Count the total number of email items in the PST, broken down by folder.

    Args:
        pst_path: Absolute path to the .pst file (defaults to built-in sample).
    """
    try:
        return await asyncio.to_thread(_count_emails_sync, pst_path or DEFAULT_PST)
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


@mcp.tool()
async def draft_email(
    subject: str = "",
    body: str = "",
    to_addresses: str = "",
    cc_addresses: str = "",
    bcc_addresses: str = "",
    from_address: Optional[str] = None,
    body_file: Optional[str] = None,
    out_path: Optional[str] = None,
    file_format: str = "msg",
    append_to_pst: Optional[str] = None,
) -> str:
    """Create an unsent draft email (MSG/EML file and/or add to PST Drafts folder).

    Args:
        subject: Message subject.
        body: Plain-text body (ignored if body_file is set).
        to_addresses: Comma-separated To addresses.
        cc_addresses: Comma-separated Cc addresses.
        bcc_addresses: Comma-separated Bcc addresses.
        from_address: Optional From address.
        body_file: Path to a UTF-8 file on the server to use as body.
        out_path: Save draft to this file path (.msg or .eml).
        file_format: "msg" or "eml" (default "msg").
        append_to_pst: Also append the draft to this PST's Drafts folder.
    """
    if not out_path and not append_to_pst:
        return "Error: specify at least one of out_path or append_to_pst."
    fmt = (file_format or "msg").lower()
    if fmt not in ("msg", "eml"):
        return f"Error: file_format must be msg or eml, got {file_format!r}"
    try:
        return await asyncio.to_thread(
            run_draft_to_string,
            subject,
            body,
            body_file,
            to_addresses,
            cc_addresses or None,
            bcc_addresses or None,
            from_address,
            out_path,
            fmt,
            append_to_pst,
        )
    except Exception as ex:
        return f"Error: {type(ex).__name__}: {ex}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Outlook PST MCP Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=os.environ.get("MCP_EXTRACT_PST_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_EXTRACT_PST_PORT", "9003")))
    parser.add_argument("--path", default=os.environ.get("MCP_EXTRACT_PST_PATH", "/mcp"))
    args = parser.parse_args()

    print(
        Fore.GREEN +
        f"[mcp-server] ExtractPstMCP  →  "
        f"http://{args.host}:{args.port}{args.path}"
    )
    print(Fore.CYAN + f"[mcp-server] Default PST: {DEFAULT_PST}")
    print(Fore.YELLOW + "[mcp-server] Reachable from sandbox via host's LAN/bridge IP on that port.")
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        path=args.path,
        show_banner=False,
    )
