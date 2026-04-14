#!/usr/bin/env python3
"""
Tier 3 Enrichment — consultative inference via Ollama API.

Provides:
  ConsultationClient  — low-level Ollama API wrapper
  Tier3Enricher       — enriches AnalystConsensus objects with LLM synthesis

Activated when INVESTORCLAW_CONSULTATION_ENABLED=true.
Environment variables:
  INVESTORCLAW_CONSULTATION_ENDPOINT  (default: http://localhost:11434)
  INVESTORCLAW_CONSULTATION_MODEL     (default: gemma4-consult)
  INVESTORCLAW_CARD_FORMAT            (default: both)
    Controls what artifact is written per enriched symbol:
      json  — write ~/.investorclaw/quotes/{SYMBOL}.quote.json only; no SVG.
              Safe for mobile/messaging channels (WhatsApp, Signal, Telegram)
              where SVG is unsupported or undesirable.
      svg   — write SVG card only (requires INVESTOR_CLAW_REPORTS_DIR).
              Legacy behaviour; no persistent text artifact.
      both  — write JSON quote file always + SVG if INVESTOR_CLAW_REPORTS_DIR
              is set. Default for desktop/web sessions.

gemma4-consult is a tuned Ollama derivative of gemma4:e4b optimised for
low-latency consultative Q&A (num_ctx=2048, num_predict=600, ~65 tok/s on
RTX 4500 Ada 24 GB).  Create it with: ollama create gemma4-consult -f Modelfile

Tested models (via Ollama):
  gemma4-consult   — recommended; tuned gemma4:e4b, fast (~65 tok/s)
  gemma4:e4b       — base model; good quality/speed tradeoff, 128K ctx
  nemotron-3-nano  — suitable for lower-VRAM setups
  qwen2.5:14b      — solid alternative

Other Ollama-compatible models will likely work. Model behaviour varies —
run /portfolio setup to auto-detect what is available on your endpoint.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Sentence splitter that avoids breaking on decimal numbers like $587.31
_SENT_RE = re.compile(r'(?<!\d)\.(?!\d)\s*')


def _get_hmac_key() -> bytes:
    key = os.environ.get("INVESTORCLAW_CONSULTATION_HMAC_KEY", "").strip()
    if key:
        return key.encode()
    # Check user-space config, never read or write the repo-local .env
    env_file = Path.home() / ".investorclaw" / ".env"
    if env_file.exists():
        existing = env_file.read_text()
        for line in existing.splitlines():
            if line.strip().startswith("INVESTORCLAW_CONSULTATION_HMAC_KEY="):
                found_key = line.strip().split("=", 1)[1].strip()
                if found_key:
                    os.environ["INVESTORCLAW_CONSULTATION_HMAC_KEY"] = found_key
                    return found_key.encode()
    generated = secrets.token_hex(32)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "a") as f:
        f.write(f"\nINVESTORCLAW_CONSULTATION_HMAC_KEY={generated}\n")
    os.environ["INVESTORCLAW_CONSULTATION_HMAC_KEY"] = generated
    return generated.encode()


def _compute_fingerprint(symbol: str, model: str, synthesis: str) -> str:
    key = _get_hmac_key()
    msg = f"{symbol}|{model}|{synthesis}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class ConsultationResult:
    """Result from a single local-inference inference call."""
    response: str
    model: str
    endpoint: str
    inference_ms: int
    is_heuristic: bool = False

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "endpoint": self.endpoint,
            "inference_ms": self.inference_ms,
            "is_heuristic": self.is_heuristic,
        }


@dataclass
class EnrichedAnalystConsensus:
    """AnalystConsensus enriched with LLM synthesis fields."""
    # Mirror of AnalystConsensus core fields
    symbol: str
    current_price: float
    analyst_count: int
    consensus: Optional[str]          # consensus_recommendation
    recommendation_mean: float

    # Enrichment fields
    sentiment_label: str = "neutral"
    sentiment_score: float = 0.0
    recommendation_strength: str = "moderate"
    synthesis: str = ""
    key_insights: List[str] = field(default_factory=list)
    risk_assessment: str = ""
    consultation: Optional[dict] = None
    fingerprint: str = ""
    quote: Optional[dict] = None


# ---------------------------------------------------------------------------
# ConsultationClient
# ---------------------------------------------------------------------------

class ConsultationClient:
    """Thin wrapper around the local-inference Ollama generate API."""

    def __init__(self) -> None:
        self.endpoint = os.environ.get(
            "INVESTORCLAW_CONSULTATION_ENDPOINT", "http://localhost:11434"
        ).rstrip("/")
        self.model = os.environ.get(
            "INVESTORCLAW_CONSULTATION_MODEL", "gemma4-consult"
        )

    def is_available(self) -> bool:
        """Probe GET /api/tags — returns True if Ollama is reachable."""
        try:
            req = urllib.request.Request(f"{self.endpoint}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.debug("local-inference probe failed: %s", exc)
            return False

    def consult(self, prompt: str, timeout: int = 120) -> ConsultationResult:
        """POST to /api/generate and return ConsultationResult."""
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read())
            inference_ms = int((time.time() - t0) * 1000)
            return ConsultationResult(
                response=body.get("response", ""),
                model=self.model,
                endpoint=self.endpoint,
                inference_ms=inference_ms,
                is_heuristic=False,
            )
        except Exception as exc:
            inference_ms = int((time.time() - t0) * 1000)
            logger.warning("local-inference inference failed: %s", exc)
            return ConsultationResult(
                response="",
                model=self.model,
                endpoint=self.endpoint,
                inference_ms=inference_ms,
                is_heuristic=True,
            )


# ---------------------------------------------------------------------------
# Tier3Enricher
# ---------------------------------------------------------------------------

class Tier3Enricher:
    """Enriches AnalystConsensus objects with local-inference LLM synthesis."""

    def __init__(self) -> None:
        self.client = ConsultationClient()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sentiment_from_consensus(consensus: Optional[str]) -> tuple[str, float]:
        """Map consensus string to (label, score)."""
        if not consensus:
            return "neutral", 0.0
        c = consensus.lower()
        if "strong buy" in c:
            return "positive", 0.9
        if "buy" in c:
            return "positive", 0.7
        if "hold" in c or "neutral" in c:
            return "neutral", 0.0
        if "strong sell" in c:
            return "negative", -0.9
        if "sell" in c or "underperform" in c:
            return "negative", -0.7
        return "neutral", 0.0

    @staticmethod
    def _strength_from_mean(recommendation_mean: float) -> str:
        """Map 1-5 Finnhub/Yahoo recommendation_mean to strength label."""
        if recommendation_mean is None:
            return "neutral"
        if recommendation_mean <= 1.5:
            return "strong_buy"
        if recommendation_mean <= 2.5:
            return "buy"
        if recommendation_mean <= 3.5:
            return "hold"
        if recommendation_mean <= 4.5:
            return "sell"
        return "strong_sell"

    def _build_prompt(self, symbol: str, rec: Any) -> str:
        """Build a compact analyst synthesis prompt."""
        return (
            f"You are a financial data analyst. Summarize the analyst sentiment for {symbol}. "
            f"Consensus: {getattr(rec, 'consensus_recommendation', 'N/A')}. "
            f"Analysts: {getattr(rec, 'analyst_count', 0)}. "
            f"Buy/Hold/Sell: {getattr(rec, 'buy_count', 0)}/{getattr(rec, 'hold_count', 0)}/{getattr(rec, 'sell_count', 0)}. "
            f"Mean target: ${getattr(rec, 'target_price_mean', 0) or 0:.2f}. "
            f"Current: ${getattr(rec, 'current_price', 0):.2f}. "
            "In 2 sentences: (1) key analyst view, (2) main risk. "
            "Educational only — not investment advice."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enrich_batch(
        self,
        recommendations: Dict[str, Any],
        limit: Optional[int] = None,
    ) -> Dict[str, EnrichedAnalystConsensus]:
        """
        Enrich a dict of AnalystConsensus objects with LLM synthesis.

        Args:
            recommendations: {symbol: AnalystConsensus}
            limit: cap number of symbols enriched (None = all)

        Returns:
            {symbol: EnrichedAnalystConsensus}
        """
        enriched: Dict[str, EnrichedAnalystConsensus] = {}

        symbols = list(recommendations.keys())
        if limit is not None:
            symbols = symbols[:limit]

        for symbol in symbols:
            rec = recommendations[symbol]
            sentiment_label, sentiment_score = self._sentiment_from_consensus(
                getattr(rec, "consensus_recommendation", None)
            )
            strength = self._strength_from_mean(
                getattr(rec, "recommendation_mean", 2.5)
            )

            synthesis = ""
            key_insights: List[str] = []
            risk_assessment = ""
            consultation_meta: Optional[dict] = None

            fp = ""
            quote_block: Optional[dict] = None

            if self.client.is_available():
                prompt = self._build_prompt(symbol, rec)
                result = self.client.consult(prompt)
                if result.response:
                    synthesis = result.response.strip()
                    sentences = [s.strip() for s in _SENT_RE.split(synthesis) if s.strip()]
                    key_insights = sentences[:2]
                    risk_assessment = sentences[-1] if len(sentences) > 1 else synthesis
                    fp = _compute_fingerprint(symbol, self.client.model, synthesis)
                    attribution = f"{self.client.model} via local-inference ({result.inference_ms}ms)"
                    quote_block = {
                        "text": synthesis,
                        "attribution": attribution,
                        "verbatim_required": True,
                        "fingerprint": fp,
                    }
                    _card_fmt = os.environ.get("INVESTORCLAW_CARD_FORMAT", "both").strip().lower()

                    # JSON quote file — written unless format is svg-only.
                    # No env var dependency; no render module. Canonical text artifact.
                    if _card_fmt != "svg":
                        try:
                            _quote_dir = Path.home() / ".investorclaw" / "quotes"
                            _quote_dir.mkdir(parents=True, exist_ok=True)
                            _quote_file = _quote_dir / f"{symbol}.quote.json"
                            _quote_file.write_text(json.dumps({
                                "symbol": symbol,
                                "text": synthesis,
                                "attribution": attribution,
                                "fingerprint": fp,
                                "verbatim_required": True,
                                "timestamp": datetime.now().isoformat(),
                            }, indent=2))
                            quote_block["quote_path"] = str(_quote_file)
                        except Exception as _qe:
                            logger.warning("Quote JSON write failed for %s: %s", symbol, _qe)

                    # SVG card — written only when format is not json-only AND
                    # INVESTOR_CLAW_REPORTS_DIR is set.
                    if _card_fmt != "json":
                        _rdir = os.environ.get("INVESTOR_CLAW_REPORTS_DIR", "")
                        if _rdir:
                            try:
                                from rendering.render_consultation_card import render_card
                                card_path = str(render_card(
                                    symbol, synthesis, attribution, fp,
                                    datetime.now().isoformat(),
                                    Path(_rdir) / ".raw",
                                ))
                                quote_block["card_path"] = card_path
                            except Exception as _e:
                                logger.debug("Card render failed for %s: %s", symbol, _e)
                consultation_meta = result.to_dict()
            else:
                consultation_meta = {
                    "model": self.client.model,
                    "endpoint": self.client.endpoint,
                    "inference_ms": 0,
                    "is_heuristic": True,
                }

            enriched[symbol] = EnrichedAnalystConsensus(
                symbol=symbol,
                current_price=getattr(rec, "current_price", 0.0),
                analyst_count=getattr(rec, "analyst_count", 0),
                consensus=getattr(rec, "consensus_recommendation", None),
                recommendation_mean=getattr(rec, "recommendation_mean", 2.5),
                sentiment_label=sentiment_label,
                sentiment_score=sentiment_score,
                recommendation_strength=strength,
                synthesis=synthesis,
                key_insights=key_insights,
                risk_assessment=risk_assessment,
                consultation=consultation_meta,
                fingerprint=fp,
                quote=quote_block,
            )

        return enriched
