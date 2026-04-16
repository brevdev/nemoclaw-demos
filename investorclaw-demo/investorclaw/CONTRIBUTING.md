# Contributing to InvestorClaw

Thank you for considering a contribution. InvestorClaw is an OpenClaw portfolio
analysis skill. Contributions that improve accuracy, reliability, and educational
value are welcome.

---

## Before you start

- Read [README.md](README.md) to understand the project scope and design intent.
- Review the [Security Policy](SECURITY.md) before submitting anything security-related.
- Check open issues and pull requests to avoid duplicate work.

---

## What we accept

- Bug fixes (calculation errors, provider failures, edge-case crashes)
- New market data provider integrations (must not break existing fallback chain)
- Additional bond analytics or performance metrics (with cited methodology)
- Documentation improvements and clarification
- Test coverage improvements
- Accessibility and mobile improvements to the EOD report template

## What we do not accept

- Features that produce output resembling investment advice, suitability
  assessments, or specific buy/sell recommendations — all output must remain
  strictly educational.
- Changes that remove or weaken the disclaimer wrapper on any analysis output.
- Hard-coded portfolio paths, API keys, or personal account data of any kind.
- Dependencies with GPL/AGPL licenses (MIT-compatible only).

---

## Development setup

```bash
git clone https://github.com/perlowja/InvestorClaw.git
cd InvestorClaw
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in at least one market data key to run integration paths
pytest tests/ -v
python3 tests_smoke.py
```

CI runs `pytest` on Python 3.9–3.12 for every push and pull request
(`.github/workflows/test.yml`).

---

## Pull request checklist

- [ ] `pytest tests/ -v` passes locally
- [ ] `python3 tests_smoke.py` passes locally
- [ ] No personal data (account names, holdings quantities, real portfolio values)
      appears anywhere in the diff — see [Security Policy](SECURITY.md)
- [ ] Any new `.env` variable is documented in both `.env.example` and the
      Configuration Reference section of `README.md`
- [ ] New or changed analysis output includes `"is_investment_advice": false` and
      the standard disclaimer wrapper
- [ ] Docstrings do not use "fiduciary", "advice", "recommend", "suitable for you",
      or specific action verbs directed at the user's financial decisions
- [ ] Commit messages follow the project convention:
      `type(scope): short description` (e.g. `fix(bonds): correct YTM clipping`)

---

## Disclaimer language rules

InvestorClaw enforces educational-only output. When adding or changing text that
will appear in reports, agent responses, or docstrings:

- Use: "educational analysis", "informational context", "historical data",
  "consider discussing with a financial advisor"
- Avoid: "you should", "we recommend", "this is suitable for", "fiduciary",
  specific buy/sell/hold calls, target-price projections presented as guidance

The guardrails in `data/guardrails.yaml` enforce this at runtime. Contributions
must not circumvent them.

---

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE) that covers this project.
