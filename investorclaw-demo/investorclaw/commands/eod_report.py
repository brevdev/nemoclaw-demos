#!/usr/bin/env python3
"""
commands/eod_report.py — End-of-Day Portfolio Report

Assembles today's portfolio analysis outputs into a formatted HTML email
(and optional PDF) delivered via SMTP, gog (Google CLI), or saved to disk.

Default behaviour (no --run):
  Reads existing JSON outputs from today's reports directory.
  Use this mode when all commands have already run during the day.

With --run:
  Executes the full command pipeline first (holdings → analyst → news →
  bonds → performance → synthesize), then generates the report.
  Designed for automated after-hours scheduling when no prior run exists.

SMTP configuration (via environment or .env):
  SMTP_HOST        SMTP server hostname (e.g. smtp.gmail.com)
  SMTP_PORT        Port — 465 for SSL, 587 for TLS (default: 587)
  SMTP_USER        Login username
  SMTP_PASS        Login password / app password
  SMTP_FROM        From address (defaults to SMTP_USER)
  EOD_EMAIL_TO     Recipient address (required for email delivery)
  INVESTOR_CLAW_EOD_PDF   Set to "true" to attach PDF (requires weasyprint)

gog delivery (alternative to SMTP — requires: brew install gogcli):
  Use --via-gog to send via the gog Google CLI (no SMTP config needed).
  Automatically used as fallback when SMTP is not configured and gog is available.
  Authorize once with: gog auth add your@gmail.com --services gmail

Usage examples:
  python3 eod_report.py                         # report-only from existing outputs
  python3 eod_report.py --run                   # full pipeline + report
  python3 eod_report.py --email-to me@example.com
  python3 eod_report.py --email-to me@gmail.com --via-gog
  python3 eod_report.py --run --pdf --email-to me@example.com
  python3 eod_report.py --no-email --output html_only.html
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import smtplib
import subprocess
import sys
import time
from datetime import date as _date
from email import encoders as email_encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Bootstrap path so we can import project modules
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline commands (in dependency order)
# ---------------------------------------------------------------------------

_PIPELINE_COMMANDS: List[str] = [
    "holdings",
    "analyst",
    "news",
    "bonds",
    "performance",
    "synthesize",
]


def _run_pipeline(investorclaw_py: Path, reports_dir: Path) -> float:
    """
    Run the full analysis pipeline via the investorclaw.py entry point.

    Returns total elapsed seconds.
    """
    t0 = time.perf_counter()
    env = os.environ.copy()
    # Ensure all commands write to the same dated directory
    env["INVESTOR_CLAW_RUN_DATE"] = _date.today().isoformat()
    if "INVESTOR_CLAW_REPORTS_DIR" not in env:
        env["INVESTOR_CLAW_REPORTS_DIR"] = str(reports_dir.parent)

    for cmd in _PIPELINE_COMMANDS:
        logger.info("Running: %s %s", investorclaw_py.name, cmd)
        result = subprocess.run(
            [sys.executable, str(investorclaw_py), cmd],
            env=env,
            cwd=str(_ROOT),
        )
        if result.returncode != 0:
            logger.warning("Command '%s' exited with code %d — continuing", cmd, result.returncode)

    return time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load(path: Path) -> Optional[dict]:
    """Load a JSON file, returning None on any error."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception as exc:
        logger.debug("Could not load %s: %s", path, exc)
        return None


def _find_fallback(filename: str, base_dir: Path, max_days: int = 7) -> Optional[Path]:
    """
    Walk sibling dated directories (YYYY-MM-DD) newest-first looking for *filename*.

    Returns the first match found within *max_days* of *base_dir*, or None.
    Used when today's analysis hasn't been run yet but yesterday's data is valid
    (e.g., Sunday — no new market data since Friday's close).
    """
    parent = base_dir.parent
    try:
        siblings = sorted(
            [d for d in parent.iterdir() if d.is_dir() and d != base_dir and len(d.name) == 10],
            reverse=True,
        )
    except Exception:
        return None
    for sib in siblings[:max_days]:
        candidate = sib / filename
        if candidate.exists():
            return candidate
    return None


def _load_report_data(reports_dir: Path) -> Dict[str, Any]:
    """
    Load all available JSON outputs from *reports_dir*.

    When a file is missing from *reports_dir*, falls back to the most recent
    dated sibling directory (up to 7 days back).  This handles the common case
    where holdings were refreshed today but news/analyst/bonds/performance
    haven't been re-run yet.

    Missing files with no fallback are set to empty dicts.
    """
    filenames = {
        "holdings":    "holdings_summary.json",
        "analyst":     "analyst_recommendations_summary.json",
        "analyst_raw": "analyst_data.json",
        "news":        "portfolio_news.json",
        "bonds":       "bond_analysis.json",
        "performance": "performance.json",
    }

    data: Dict[str, Any] = {}
    for key, filename in filenames.items():
        path = reports_dir / filename
        loaded = _load(path)
        if loaded is None:
            fallback = _find_fallback(filename, reports_dir)
            if fallback:
                loaded = _load(fallback)
                if loaded is not None:
                    logger.info("Using fallback for %s: %s", filename, fallback.parent.name)
        if loaded is None:
            logger.debug("Missing report file (no fallback): %s", filename)
            data[key] = {}
        else:
            data[key] = loaded
        if key == "analyst_raw":
            # Merge analyst detail into analyst key for convenience
            if loaded and "recommendations" not in data.get("analyst", {}):
                data["analyst"]["recommendations"] = loaded.get("recommendations", {})

    return data


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _assemble_report(reports_dir: Path, run_duration_s: float = 0) -> str:
    """
    Build the HTML email string from today's outputs.

    Returns HTML string.
    """
    from commands.fa_discussion import extract_fa_topics
    from rendering.eod_email_template import render_eod_email

    raw_data = _load_report_data(reports_dir)
    fa_topics = extract_fa_topics(reports_dir, preloaded=raw_data)

    report_data: Dict[str, Any] = {
        "date":           _date.today().isoformat(),
        "holdings":       raw_data.get("holdings", {}),
        "analyst":        raw_data.get("analyst", {}),
        "news":           raw_data.get("news", {}),
        "bonds":          raw_data.get("bonds") or None,
        "performance":    raw_data.get("performance", {}),
        "fa_topics":      fa_topics,
        "run_duration_s": run_duration_s,
    }

    return render_eod_email(report_data)


# ---------------------------------------------------------------------------
# PDF generation (optional dependency: weasyprint)
# ---------------------------------------------------------------------------

def _generate_pdf(html: str, output_path: Path) -> bool:
    """
    Convert *html* to PDF at *output_path*.

    Returns True on success, False if weasyprint is not installed.
    """
    try:
        from weasyprint import HTML as WP_HTML  # type: ignore
        WP_HTML(string=html).write_pdf(str(output_path))
        logger.info("PDF saved: %s", output_path)
        return True
    except ImportError:
        logger.warning(
            "weasyprint not installed — PDF generation skipped. "
            "Install with: pip install weasyprint"
        )
        return False
    except Exception as exc:
        logger.warning("PDF generation failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# SMTP delivery
# ---------------------------------------------------------------------------

def _send_email(
    html: str,
    subject: str,
    to_addr: str,
    pdf_path: Optional[Path] = None,
) -> bool:
    """
    Send the HTML report via SMTP.

    Reads configuration from environment variables:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM

    Returns True on success.
    """
    host  = os.environ.get("SMTP_HOST", "").strip()
    port  = int(os.environ.get("SMTP_PORT", "587"))
    user  = os.environ.get("SMTP_USER", "").strip()
    pwd   = os.environ.get("SMTP_PASS", "").strip()
    from_ = os.environ.get("SMTP_FROM", user).strip()

    if not host or not user or not pwd:
        logger.error(
            "SMTP not configured. Set SMTP_HOST, SMTP_USER, and SMTP_PASS in .env "
            "to enable email delivery."
        )
        return False

    msg = MIMEMultipart("alternative" if not pdf_path else "mixed")
    msg["Subject"] = subject
    msg["From"]    = from_
    msg["To"]      = to_addr

    # Attach HTML body
    msg.attach(MIMEText(html, "html", "utf-8"))

    # Attach PDF if provided and exists
    if pdf_path and pdf_path.exists():
        with open(pdf_path, "rb") as fh:
            pdf_part = MIMEBase("application", "pdf")
            pdf_part.set_payload(fh.read())
        email_encoders.encode_base64(pdf_part)
        pdf_part.add_header(
            "Content-Disposition",
            "attachment",
            filename=pdf_path.name,
        )
        msg.attach(pdf_part)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as smtp:
                smtp.login(user, pwd)
                smtp.sendmail(from_, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(host, port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(user, pwd)
                smtp.sendmail(from_, [to_addr], msg.as_string())

        logger.info("EOD report emailed to %s", to_addr)
        return True

    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False


# ---------------------------------------------------------------------------
# gog delivery (Google CLI — alternative to SMTP)
# ---------------------------------------------------------------------------

def _send_email_gog(
    html: str,
    subject: str,
    to_addr: str,
    account: Optional[str] = None,
    pdf_path: Optional[Path] = None,
) -> bool:
    """
    Send the HTML report via the `gog` Google CLI tool.

    Requires `gog` binary (brew install gogcli) and a valid authorized account
    (run `gog auth add EMAIL --services gmail` once to authorize).

    Returns True on success.
    """
    gog_bin = shutil.which("gog")
    if not gog_bin:
        logger.error(
            "gog binary not found. Install with: brew install gogcli  "
            "then: gog auth add EMAIL --services gmail"
        )
        return False

    cmd = [
        gog_bin, "gmail", "send",
        "--to", to_addr,
        "--subject", subject,
        "--body-html", html,
        "-j",
    ]
    if account:
        cmd += ["-a", account]
    if pdf_path and pdf_path.exists():
        cmd += ["--attach", str(pdf_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                logger.info("EOD report emailed to %s via gog (messageId: %s)", to_addr, data.get("messageId", "?"))
            except Exception:
                logger.info("EOD report emailed to %s via gog", to_addr)
            return True
        else:
            logger.error("gog send failed: %s", (result.stderr or result.stdout).strip())
            return False
    except Exception as exc:
        logger.error("gog send error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="InvestorClaw end-of-day portfolio report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run the full analysis pipeline before generating the report",
    )
    parser.add_argument(
        "--email-to",
        metavar="ADDRESS",
        default=os.environ.get("EOD_EMAIL_TO", "").strip(),
        help="Recipient email address (default: EOD_EMAIL_TO env var)",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Save report to file only (skip email delivery)",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        default=os.environ.get("INVESTOR_CLAW_EOD_PDF", "").lower() in ("1", "true", "yes"),
        help="Generate a PDF attachment (requires weasyprint)",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Path to save HTML report (default: <reports_dir>/eod_report_<date>.html)",
    )
    parser.add_argument(
        "--via-gog",
        action="store_true",
        default=os.environ.get("INVESTOR_CLAW_EOD_GOG", "").lower() in ("1", "true", "yes"),
        help="Send via gog Google CLI instead of SMTP (requires: brew install gogcli)",
    )
    parser.add_argument(
        "--gog-account",
        metavar="EMAIL",
        default=os.environ.get("INVESTOR_CLAW_GOG_ACCOUNT", "").strip(),
        help="gog account email to use for sending (default: auto-detected)",
    )
    parser.add_argument(
        "--reports-dir",
        metavar="DIR",
        help="Override reports directory (default: today's dated dir)",
    )
    args = parser.parse_args()

    # ── Load .env if present ──────────────────────────────────────────────
    _env_file = _ROOT / ".env"
    if _env_file.exists():
        try:
            with open(_env_file) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        if k.strip() not in os.environ:
                            os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass

    # ── Resolve directories ───────────────────────────────────────────────
    from config.path_resolver import get_reports_dir

    reports_dir = Path(args.reports_dir).expanduser() if args.reports_dir else get_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    investorclaw_py = _ROOT / "investorclaw.py"

    # ── Run pipeline if requested ─────────────────────────────────────────
    run_duration_s = 0.0
    if args.run:
        logger.info("Running full analysis pipeline …")
        run_duration_s = _run_pipeline(investorclaw_py, reports_dir)
        logger.info("Pipeline complete in %.0f seconds", run_duration_s)

    # ── Assemble HTML report ──────────────────────────────────────────────
    logger.info("Assembling EOD report from: %s", reports_dir)
    html = _assemble_report(reports_dir, run_duration_s)

    # ── Save HTML ─────────────────────────────────────────────────────────
    today = _date.today().isoformat()
    html_path = (
        Path(args.output).expanduser()
        if args.output
        else reports_dir / f"eod_report_{today.replace('-', '')}.html"
    )
    html_path.write_text(html, encoding="utf-8")
    logger.info("HTML report saved: %s", html_path)

    # ── Generate PDF ──────────────────────────────────────────────────────
    pdf_path: Optional[Path] = None
    if args.pdf:
        pdf_path = html_path.with_suffix(".pdf")
        _generate_pdf(html, pdf_path)

    # ── Send email ────────────────────────────────────────────────────────
    if not args.no_email and args.email_to:
        subject = f"InvestorClaw Portfolio Report — {today}"
        smtp_configured = bool(
            os.environ.get("SMTP_HOST", "").strip()
            and os.environ.get("SMTP_USER", "").strip()
            and os.environ.get("SMTP_PASS", "").strip()
        )
        if args.via_gog or not smtp_configured:
            # Use gog when explicitly requested or when SMTP isn't configured
            gog_account = args.gog_account or (
                args.email_to if "@gmail.com" in args.email_to else None
            )
            if not _send_email_gog(html, subject, args.email_to, gog_account, pdf_path):
                if smtp_configured:
                    logger.info("Falling back to SMTP delivery …")
                    _send_email(html, subject, args.email_to, pdf_path)
        else:
            _send_email(html, subject, args.email_to, pdf_path)
    elif not args.no_email and not args.email_to:
        logger.info(
            "No recipient configured — skipping email delivery. "
            "Use --email-to or set EOD_EMAIL_TO in .env to enable."
        )

    # ── ic_result envelope ────────────────────────────────────────────────
    smtp_configured = bool(
        os.environ.get("SMTP_HOST", "").strip()
        and os.environ.get("SMTP_USER", "").strip()
        and os.environ.get("SMTP_PASS", "").strip()
    )
    delivery_method = None
    if not args.no_email and args.email_to:
        delivery_method = "gog" if (args.via_gog or not smtp_configured) else "smtp"

    print(json.dumps({
        "ic_result": {
            "report_type": "eod_report",
            "date": today,
            "html_path": str(html_path),
            "pdf_path": str(pdf_path) if pdf_path and pdf_path.exists() else None,
            "emailed_to": args.email_to if not args.no_email and args.email_to else None,
            "delivery_method": delivery_method,
            "pipeline_run": args.run,
            "pipeline_duration_s": round(run_duration_s, 1),
        }
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
