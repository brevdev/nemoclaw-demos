#!/usr/bin/env python3
"""Submission smoke test for InvestorClaw.

Checks the basics ClawHub reviewers and cold installs care about:
- required repo files exist
- plugin manifest parses and matches core metadata
- routed commands resolve to real scripts
- entrypoint help runs successfully
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED_FILES = [
    "openclaw.plugin.json",
    "package.json",
    "SKILL.md",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "investorclaw.py",
    "index.ts",
    "dist/index.js",
]


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def ok(msg: str) -> None:
    print(f"OK: {msg}")


def main() -> int:
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if not path.exists():
            return fail(f"missing required file: {rel}")
        ok(f"found {rel}")

    plugin = json.loads((ROOT / "openclaw.plugin.json").read_text())
    if plugin.get("id") != "investorclaw":
        return fail("plugin id must be 'investorclaw'")
    ok("plugin id is investorclaw")

    if plugin.get("version") != "1.0.0":
        return fail("plugin version must be 1.0.0")
    ok("plugin version is 1.0.0")

    if plugin.get("homepage") != "https://github.com/perlowja/InvestorClaw":
        return fail("plugin homepage is not canonical GitHub URL")
    ok("plugin homepage matches canonical repo")

    oc = plugin.get("openclaw", {})
    if "./" not in oc.get("skills", []):
        return fail("openclaw.skills must include './'")
    ok("plugin skills entry present")

    # Verify openclaw.plugin.json and package.json agree on extension artifact
    pkg = json.loads((ROOT / "package.json").read_text())
    plugin_ext = (oc.get("extensions") or [""])[0]
    pkg_ext = (pkg.get("openclaw", {}).get("extensions") or [""])[0]
    if plugin_ext != pkg_ext:
        return fail(
            f"manifest extension mismatch: openclaw.plugin.json={plugin_ext!r} "
            f"vs package.json={pkg_ext!r} — both must point to the same artifact"
        )
    if "dist/" not in plugin_ext:
        return fail(
            f"plugin extension must point into dist/ (got {plugin_ext!r}); "
            "run 'npm run build' or 'tsc' and commit dist/index.js"
        )
    ok(f"manifest extensions consistent ({plugin_ext})")

    # Verify versions match
    if plugin.get("version") != pkg.get("version"):
        return fail(
            f"version mismatch: openclaw.plugin.json={plugin.get('version')!r} "
            f"vs package.json={pkg.get('version')!r}"
        )
    ok("manifest versions consistent")

    sys.path.insert(0, str(ROOT))
    from runtime.router import COMMANDS, resolve_script  # noqa: WPS433

    scripts_dir = ROOT / "commands"
    for command in sorted(COMMANDS):
        script = resolve_script(command, scripts_dir)
        if script is None:
            return fail(f"command does not resolve: {command}")
        if not script.exists():
            return fail(f"resolved script missing for {command}: {script}")
    ok(f"resolved {len(COMMANDS)} commands")

    result = subprocess.run(
        [sys.executable, str(ROOT / "investorclaw.py"), "help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return fail(f"help command failed: {result.stderr.strip() or result.stdout.strip()}")
    if "Usage: /portfolio <command>" not in result.stdout:
        return fail("help output missing usage header")
    ok("entrypoint help command succeeded")

    # ------------------------------------------------------------------
    # Test: ic_result envelope present in guardrails output
    # ------------------------------------------------------------------
    ic_result = subprocess.run(
        [sys.executable, str(ROOT / "investorclaw.py"), "guardrails"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = ic_result.stdout + ic_result.stderr
    if '"ic_result"' not in combined:
        return fail("ic_result envelope missing from guardrails output")
    ok("ic_result envelope present in guardrails output")

    # ------------------------------------------------------------------
    # Test: HMAC fingerprint returns 16-char hex string
    # ------------------------------------------------------------------
    sys.path.insert(0, str(ROOT))
    try:
        from internal.tier3_enrichment import _compute_fingerprint
        fp = _compute_fingerprint("MSFT", "gemma4-consult", "test synthesis")
        if len(fp) != 16:
            return fail(f"HMAC fingerprint wrong length: {len(fp)} (expected 16)")
        int(fp, 16)  # must be valid hex
    except Exception as e:
        return fail(f"HMAC fingerprint test failed: {e}")
    ok("HMAC fingerprint returns 16-char hex string")

    # ------------------------------------------------------------------
    # Test: dynamic consultation limit tiers
    # ------------------------------------------------------------------
    try:
        from services.consultation_policy import get_dynamic_consultation_limit
        cases = [(10, 10), (30, 30), (100, 40), (250, 20)]
        for position_count, expected in cases:
            got = get_dynamic_consultation_limit(position_count)
            if got != expected:
                return fail(f"get_dynamic_consultation_limit({position_count}) = {got}, expected {expected}")
    except Exception as e:
        return fail(f"dynamic consultation limit test failed: {e}")
    ok("dynamic consultation limit tiers correct")

    # ------------------------------------------------------------------
    # Test: enrichment_status defaults when no progress file
    # ------------------------------------------------------------------
    try:
        from services.consultation_policy import get_enrichment_status
        with tempfile.TemporaryDirectory() as tmp:
            status = get_enrichment_status(Path(tmp))
            if status.get("in_progress") is not False:
                return fail("enrichment_status in_progress should default to False")
    except Exception as e:
        return fail(f"enrichment_status defaults test failed: {e}")
    ok("enrichment_status defaults correct when no progress file")

    # ------------------------------------------------------------------
    # Test: compact synthesis_basis field and enrichment_status block
    # ------------------------------------------------------------------
    try:
        from rendering.compact_serializers import serialize_analyst_compact
        mock_payload = {
            "disclaimer": "EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE",
            "timestamp": "2026-04-10T00:00:00",
            "total_symbols": 2,
            "recommendations": {
                "MSFT": {
                    "symbol": "MSFT",
                    "consensus": "Strong Buy",
                    "analyst_count": 54,
                    "current_price": 420.0,
                    "consultation": {"model": "gemma4-consult", "is_heuristic": False, "inference_ms": 3420},
                    "synthesis": "Analysts remain bullish on MSFT cloud growth.",
                    "key_insights": ["Strong Azure momentum"],
                    "risk_assessment": "Macro slowdown risk.",
                    "fingerprint": "abcd1234efgh5678",
                    "quote": {"text": "test", "attribution": "gemma4-consult", "verbatim_required": True, "fingerprint": "abcd1234efgh5678"},
                },
                "XYZ": {
                    "symbol": "XYZ",
                    "consensus": "Hold",
                    "analyst_count": 5,
                    "current_price": 10.0,
                },
            },
        }
        compact = serialize_analyst_compact(mock_payload)
        msft_basis = compact["recommendations"]["MSFT"].get("synthesis_basis")
        xyz_basis = compact["recommendations"]["XYZ"].get("synthesis_basis")
        if msft_basis != "enriched":
            return fail(f"MSFT synthesis_basis should be 'enriched', got {msft_basis!r}")
        if xyz_basis != "structured":
            return fail(f"XYZ synthesis_basis should be 'structured', got {xyz_basis!r}")
        if "enrichment_status" not in compact:
            return fail("enrichment_status block missing from compact output")
    except Exception as e:
        return fail(f"compact synthesis_basis test failed: {e}")
    ok("compact synthesis_basis and enrichment_status block correct")

    # ------------------------------------------------------------------
    # Test: INVESTORCLAW_CONSULTATION_HMAC_KEY in plugin configSchema
    # ------------------------------------------------------------------
    config_schema = plugin.get("configSchema", {})
    if "INVESTORCLAW_CONSULTATION_HMAC_KEY" not in config_schema:
        return fail("INVESTORCLAW_CONSULTATION_HMAC_KEY missing from plugin configSchema")
    ok("INVESTORCLAW_CONSULTATION_HMAC_KEY present in plugin configSchema")

    # ------------------------------------------------------------------
    # WF16: Bad argument returns non-zero exit code
    # ------------------------------------------------------------------
    try:
        bad_arg_result = subprocess.run(
            [sys.executable, str(ROOT / "investorclaw.py"), "analyst", "@@INVALID"],
            capture_output=True, text=True, timeout=15, cwd=str(ROOT)
        )
        if bad_arg_result.returncode == 0:
            return fail("WF16: investorclaw.py with @@INVALID arg returned exit code 0 (expected non-zero)")
        ok("WF16: invalid argument produces non-zero exit code")
    except Exception as e:
        return fail(f"WF16: bad-arg test failed: {e}")

    # ------------------------------------------------------------------
    # WF17: enrichment_status.display matches expected format
    # ------------------------------------------------------------------
    try:
        import re
        from rendering.compact_serializers import serialize_analyst_compact
        # Enriched record: consultation dict present with is_heuristic=False
        wf17_payload = {
            "recommendations": {
                "AAPL": {
                    "consensus": "BUY", "target_price": 200.0, "upside_pct": 12.5,
                    "analyst_count": 30,
                    "consultation": {
                        "is_heuristic": False,
                        "synthesis": "Strong fundamentals.",
                        "verbatim_required": False,
                    },
                }
            }
        }
        wf17_output = serialize_analyst_compact(wf17_payload)
        display_val = wf17_output.get("enrichment_status", {}).get("display", "")
        display_pattern = re.compile(r'^[✅⏳⚠️].+\d+/\d+\s*·\s*[\d.]+%\s*·\s*[0-9a-f]{8}')
        if not display_pattern.search(display_val):
            return fail(f"WF17: enrichment_status.display format mismatch: {display_val!r}")
        ok(f"WF17: enrichment_status.display format correct: {display_val!r}")
    except Exception as e:
        return fail(f"WF17: display format test failed: {e}")

    # ------------------------------------------------------------------
    # WF21: Unenriched symbol has synthesis_basis="structured", no consultation key
    # ------------------------------------------------------------------
    try:
        from rendering.compact_serializers import serialize_analyst_compact
        wf21_payload = {
            "recommendations": {
                "TSLA": {
                    "consensus": "HOLD", "target_price": 250.0, "upside_pct": 5.0,
                    "analyst_count": 20,
                    # No consultation key → heuristic/structured path
                }
            }
        }
        wf21_output = serialize_analyst_compact(wf21_payload)
        tsla_rec = wf21_output.get("recommendations", {}).get("TSLA", {})
        if tsla_rec.get("synthesis_basis") != "structured":
            return fail(f"WF21: expected synthesis_basis='structured', got {tsla_rec.get('synthesis_basis')!r}")
        if "consultation" in tsla_rec or "synthesis" in tsla_rec:
            return fail("WF21: unenriched record should not have consultation/synthesis key")
        ok("WF21: unenriched symbol has synthesis_basis='structured' and no consultation key")
    except Exception as e:
        return fail(f"WF21: unenriched symbol test failed: {e}")

    # ------------------------------------------------------------------
    # WF27: INVESTOR_CLAW_REPORTS_DIR env override — session writes to custom dir
    # ------------------------------------------------------------------
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = os.environ.copy()
            env["INVESTOR_CLAW_REPORTS_DIR"] = tmpdir
            env["INVESTORCLAW_AUTO_SESSION"] = "true"
            # Disable dated subdirectories so we can check the flat path predictably.
            env["INVESTOR_CLAW_DATED_REPORTS"] = "false"
            wf27_result = subprocess.run(
                [sys.executable, str(ROOT / "investorclaw.py"), "session"],
                capture_output=True, text=True, timeout=30,
                cwd=str(ROOT), env=env
            )
            session_file = Path(tmpdir) / "session_profile.json"
            if not session_file.exists():
                return fail(
                    f"WF27: session_profile.json not found in INVESTOR_CLAW_REPORTS_DIR={tmpdir}; "
                    f"exit={wf27_result.returncode}; stderr={wf27_result.stderr[:200]}"
                )
            ok(f"WF27: INVESTOR_CLAW_REPORTS_DIR override works — session_profile.json in {tmpdir}")
    except Exception as e:
        return fail(f"WF27: REPORTS_DIR override test failed: {e}")

    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
