#!/usr/bin/env python3
"""
Ollama Model Configuration for InvestorClaw GPU Inference.

Defines the gemma4-consult model configuration and provides helpers to
replicate it on any compatible Ollama endpoint.

gemma4-consult is a tuned derivative of gemma4:e4b optimised for low-latency
consultative Q&A (num_ctx=4096, num_predict=1200). It is the recommended
INVESTORCLAW_CONSULTATION_MODEL.

Benchmarked on: local-inference — RTX 4500 Ada 24 GB, driver 595.58.03
  gemma4-consult:  ~65 tok/s, simple Q&A 1.5-2.5s, complex 8-14s
  gemma4:e4b:      ~66 tok/s, 128K native context
  gemma4:e2b:      ~99 tok/s, 128K native context

Hardware requirements for gemma4-consult:
  - CUDA compute capability >= 8.0 (RTX 30xx / A-series or newer)
  - >= 12 GB VRAM (model is ~9.6 GB Q4_K_M)
  - Ollama >= 0.20.x with Flash Attention support

Usage:
  # Check what models are available on an endpoint
  python3 commands/ollama_model_config.py --check
  python3 commands/ollama_model_config.py --check --endpoint http://localhost:11434

  # Set up gemma4-consult (pulls gemma4:e4b if needed, then creates the model)
  python3 commands/ollama_model_config.py --model gemma4-consult
  python3 commands/ollama_model_config.py --model all --endpoint http://localhost:11434

  # From Python
  from commands.ollama_model_config import setup_model, get_best_available_model
  setup_model("gemma4-consult", endpoint="http://localhost:11434")
  model = get_best_available_model("http://localhost:11434")
"""
from __future__ import annotations

import logging
import os
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

#: Modelfile content for gemma4-consult — also written to docs/gemma4-consult.Modelfile
GEMMA4_CONSULT_MODELFILE = """\
FROM gemma4:e4b

PARAMETER num_ctx 4096
PARAMETER num_predict 1200
PARAMETER temperature 0.65
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER stop "<end_of_turn>"
PARAMETER stop "<eos>"

SYSTEM "You are a financial data analyst providing educational information only. Your analysis is not investment advice. Answer in 3-5 sentences for simple questions, or up to 400 words for complex topics. Lead with the direct answer. Include specific figures, percentages, and named metrics where available. No preamble, no restating the question."
"""

OLLAMA_MODELS: dict = {
    "gemma4-consult": {
        "base": "gemma4:e4b",
        "description": "Consultative Q&A — tuned gemma4:e4b derivative, ~65 tok/s, 4K ctx",
        "vram_gb_min": 12,
        "cuda_capability_min": 8.0,
        "modelfile": GEMMA4_CONSULT_MODELFILE,
        # Performance notes (RTX 4500 Ada 24 GB, driver 595.58.03)
        "benchmark": {
            "hardware": "RTX 4500 Ada 24 GB",
            "driver": "595.58.03",
            "tok_per_sec": 65,
            "simple_q_seconds": 2.0,
            "complex_q_seconds": 12.0,
            "context_tokens": 4096,
        },
    },
    "gemma4:e4b": {
        "base": None,  # pulled from Ollama registry
        "description": "Full-context reasoning — 128K ctx, ~66 tok/s",
        "vram_gb_min": 12,
        "cuda_capability_min": 8.0,
        "modelfile": None,  # use registry defaults
        "benchmark": {
            "hardware": "RTX 4500 Ada 24 GB",
            "tok_per_sec": 66,
            "context_tokens": 131072,
        },
    },
    "gemma4:e2b": {
        "base": None,
        "description": "Fast lightweight model — 128K ctx, ~99 tok/s",
        "vram_gb_min": 8,
        "cuda_capability_min": 8.0,
        "modelfile": None,
        "benchmark": {
            "hardware": "RTX 4500 Ada 24 GB",
            "tok_per_sec": 99,
            "context_tokens": 131072,
        },
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_ollama_endpoint() -> str:
    return os.environ.get(
        "INVESTORCLAW_CONSULTATION_ENDPOINT", "http://localhost:11434"
    ).rstrip("/")


def is_model_present(endpoint: str, model_name: str, timeout: int = 3) -> bool:
    """Return True if model_name is available on the Ollama endpoint."""
    try:
        resp = requests.get(f"{endpoint}/api/tags", timeout=timeout)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            target = model_name.split(":")[0]
            return any(m.get("name", "").startswith(target) for m in models)
    except Exception:
        pass
    return False


def pull_base_model(endpoint: str, model_name: str, timeout: int = 600) -> bool:
    """Pull a model from the Ollama registry."""
    logger.info(f"Pulling {model_name} from Ollama registry (this may take several minutes)...")
    try:
        resp = requests.post(
            f"{endpoint}/api/pull",
            json={"name": model_name, "stream": False},
            timeout=timeout,
        )
        if resp.status_code == 200:
            logger.info(f"Pulled {model_name}")
            return True
        logger.error(f"Pull failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Pull error: {e}")
    return False


def create_custom_model(endpoint: str, model_name: str, modelfile: str, timeout: int = 120) -> bool:
    """Create a custom Ollama model from a Modelfile string."""
    logger.info(f"Creating custom model {model_name}...")
    try:
        resp = requests.post(
            f"{endpoint}/api/create",
            json={"name": model_name, "modelfile": modelfile, "stream": False},
            timeout=timeout,
        )
        if resp.status_code == 200:
            logger.info(f"Created {model_name}")
            return True
        logger.error(f"Create failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Create error: {e}")
    return False


def setup_model(model_name: str, endpoint: str = "") -> bool:
    """
    Ensure a model is available on the given Ollama endpoint.

    For gemma4-consult: pulls gemma4:e4b base first (if absent), then
    applies the Modelfile via /api/create.

    Args:
        model_name: Key from OLLAMA_MODELS, e.g. 'gemma4-consult'
        endpoint:   Ollama API base URL. Falls back to
                    $INVESTORCLAW_CONSULTATION_ENDPOINT then localhost:11434.

    Returns:
        True if model is ready, False on failure.
    """
    config = OLLAMA_MODELS.get(model_name)
    if not config:
        logger.error(f"Unknown model: {model_name}. Available: {list(OLLAMA_MODELS)}")
        return False

    if not endpoint:
        endpoint = _default_ollama_endpoint()

    if is_model_present(endpoint, model_name):
        logger.info(f"{model_name} already available at {endpoint}")
        return True

    base = config.get("base")
    if base and not is_model_present(endpoint, base):
        if not pull_base_model(endpoint, base):
            return False

    modelfile = config.get("modelfile")
    if modelfile:
        return create_custom_model(endpoint, model_name, modelfile)

    # Registry model with no custom Modelfile
    return pull_base_model(endpoint, model_name)


def setup_all_consult_models(endpoint: str = "") -> dict:
    """
    Pull and configure all InvestorClaw GPU inference models.

    Call this to replicate the local-inference model configuration on new GPU hardware.

    Returns:
        Dict mapping model_name → bool (True = success)
    """
    if not endpoint:
        endpoint = _default_ollama_endpoint()
    results = {}
    for model_name in ["gemma4:e2b", "gemma4:e4b", "gemma4-consult"]:
        results[model_name] = setup_model(model_name, endpoint)
    return results


def get_best_available_model(endpoint: str = "") -> Optional[str]:
    """
    Return the best InvestorClaw consultation model available at this endpoint.

    Preference order: gemma4-consult → gemma4:e4b → gemma4:e2b
    Returns None if none are available.
    """
    if not endpoint:
        endpoint = _default_ollama_endpoint()
    for model in ["gemma4-consult", "gemma4:e4b", "gemma4:e2b"]:
        if is_model_present(endpoint, model):
            return model
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Setup InvestorClaw Ollama consultation models.\n\n"
            "gemma4-consult is a tuned gemma4:e4b derivative (num_ctx=4096,\n"
            "num_predict=1200, ~65 tok/s on RTX Ada). Required: 12+ GB VRAM, CUDA 8.0+."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _default_endpoint = os.environ.get(
        "INVESTORCLAW_CONSULTATION_ENDPOINT", "http://localhost:11434"
    ).rstrip("/")
    parser.add_argument(
        "--endpoint", default=_default_endpoint,
        help=(
            "Ollama API endpoint "
            "(default: $INVESTORCLAW_CONSULTATION_ENDPOINT or http://localhost:11434)"
        ),
    )
    parser.add_argument(
        "--model", default="gemma4-consult",
        help="Model to setup: gemma4-consult | gemma4:e4b | gemma4:e2b | all (default: gemma4-consult)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check model availability only — do not pull or create anything",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    if args.check:
        print(f"\nOllama endpoint: {args.endpoint}")
        best = get_best_available_model(args.endpoint)
        for model_name, config in OLLAMA_MODELS.items():
            present = is_model_present(args.endpoint, model_name)
            marker = "✅" if present else "  "
            active = " ← best available" if present and model_name == best else ""
            print(f"  {marker} {model_name:25s} {config['description']}{active}")
        if best:
            print(f"\nRecommended INVESTORCLAW_CONSULTATION_MODEL={best}")
        else:
            print("\nNo InvestorClaw models found. Run without --check to set up.")
        sys.exit(0)

    if args.model == "all":
        results = setup_all_consult_models(args.endpoint)
    else:
        results = {args.model: setup_model(args.model, args.endpoint)}

    print("\nSetup results:")
    for model, ok in results.items():
        print(f"  {'✅' if ok else '❌'}  {model}")
    sys.exit(0 if all(results.values()) else 1)
