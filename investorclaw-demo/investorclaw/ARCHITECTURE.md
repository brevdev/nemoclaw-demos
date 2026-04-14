# InvestorClaw Architecture

This document describes the current internal structure of InvestorClaw for contributors, integrators, and release reviewers.

---

## Overview

InvestorClaw is an OpenClaw skill with a thin Python entry point.
`investorclaw.py` bootstraps configuration, resolves the requested command, synthesizes default arguments, optionally primes guardrails, and dispatches to a command module under `commands/`.

```text
investorclaw.py          ← thin entry point: bootstrap + dispatch
commands/                ← one script per command
config/                  ← config loading, arg synthesis, path resolution, help text
models/                  ← portfolio, holdings, routing, and context models
providers/               ← external data providers
rendering/               ← compact serializers, disclaimers, cards, progress
runtime/                 ← router, environment, subprocess runner
services/                ← consultation policy, utilities, portfolio services
setup/                   ← first-run helpers, installer, identity updater
internal/                ← tier-3 enrichment internals
tests/                   ← unit, smoke, and contract tests
```

## Canonical Invocation

The supported invocation path is:

```bash
python3 investorclaw.py <command>
```

Directly running command modules is possible for local debugging, but the supported path is through the entry point because it centralizes environment loading, config bootstrap, synthesized arguments, and guardrail priming.

## Command Routing

The command registry lives in `runtime/router.py`.

- `COMMANDS` maps user commands and aliases to files under `commands/`
- `resolve_script()` validates and resolves the script path
- `synthesize_args()` builds default arguments from current report artifacts
- `should_prime_guardrails()` decides whether the command gets automatic guardrail priming

Representative current commands include:

- `holdings`, `performance`, `bonds`, `analyst`, `news`
- `analysis`, `synthesize`, `fixed-income`
- `session`, `lookup`, `guardrails`, `ollama-setup`
- `run` / `pipeline`

## Environment and Paths

Path resolution lives in `config/path_resolver.py`.

- `INVESTOR_CLAW_PORTFOLIO_DIR` overrides the portfolio input directory
- `INVESTOR_CLAW_REPORTS_DIR` overrides the reports output directory
- Default reports location is `~/portfolio_reports`

Bootstrap and subprocess environment setup live in:

- `runtime/bootstrap.py`
- `runtime/environment.py`
- `runtime/subprocess_runner.py`

## Consultation and Enrichment

Consultation policy is centralized in `services/consultation_policy.py`.

Key responsibilities:

- enable or disable local consultation from env
- resolve the Ollama endpoint and model
- decide whether `--tier3` is injected for a command
- calculate static or dynamic consultation limits
- expose enrichment progress metadata

At the moment, tier-3 consultation is wired for analyst-style commands through the router.

## Guardrails

InvestorClaw uses two layers of guardrails:

1. **Pre-flight priming** from `investorclaw.py` for models that need a compliance reminder before analysis commands
2. **Per-command enforcement** in the command layer and rendering/output wrappers

Guardrail content and defaults live in `data/guardrails.yaml`.

## Output Contract

Most analysis commands follow a dual-output pattern:

- compact stdout intended for the calling OpenClaw agent
- full disk artifacts intended for human review or downstream scripts

Common artifact names are synthesized by `config/command_builders.py` and written under the configured reports directory.

## Tests

Tests live under `tests/` and currently cover syntax, command contracts, env loading, router behavior, compact serializers, consultation policy, context budgets, and fingerprint logic.

Run:

```bash
pytest tests/ -v
python3 tests_smoke.py
```

## Contributor Notes

When adding or changing a command:

1. Add or update the module in `commands/`
2. Register aliases in `runtime/router.py`
3. Update synthesized defaults in `config/command_builders.py` if needed
4. Update tests for routing, command contracts, or output shape
5. Update `README.md`, `SKILL.md`, and this file if user-facing behavior changed
