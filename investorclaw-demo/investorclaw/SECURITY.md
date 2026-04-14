# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| Latest `main` | Yes |
| Older releases | No — update to `main` |

---

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email the maintainer directly at the address on the GitHub profile, or open a
[GitHub Security Advisory](https://github.com/perlowja/InvestorClaw/security/advisories/new)
(private disclosure).

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce (or a proof-of-concept, if applicable)
- The version or commit hash where you observed it

We aim to acknowledge reports within 3 business days and provide a fix or
mitigation plan within 14 days for confirmed vulnerabilities.

---

## Personal and financial data

InvestorClaw processes personal portfolio data (holdings, prices, account names).
The following rules apply to all contributors and all code in this repository:

**Never commit to this repository:**
- Personal account names, brokerage account IDs, or institution names paired
  with personal quantities
- Specific holdings quantities (share counts, dollar values, cost basis)
- Portfolio snapshots or exported CSV/XLS files containing real holdings
- API keys, tokens, or credentials of any kind (use `.env`, never committed)
- Any file whose content could identify a real individual's financial position

The `.gitignore` excludes `.env`, `~/portfolios/`, and `~/portfolio_reports/`.
These exclusions must not be removed.

**Sample / test data:**
Any sample data committed to the repository must use entirely fictional symbols,
quantities, and values with no resemblance to any real person's portfolio.

---

## Scope

| In scope | Out of scope |
|----------|-------------|
| Injection vulnerabilities in CSV/PDF parsing | Issues with third-party APIs (yfinance, Finnhub, etc.) |
| PII/financial data leakage in outputs or logs | Rate-limit behavior of external providers |
| Prompt injection via portfolio text columns | OpenClaw gateway security (report to OpenClaw) |
| Disclaimer bypass or guardrail circumvention | Broker portal or brokerage account security |
| Dependency vulnerabilities (`requirements.txt`) | |

---

## Dependency security

Run `pip audit` or `safety check` to scan for known CVEs in dependencies before
contributing changes to `requirements.txt`. Pull requests that introduce
dependencies with known critical or high CVEs will not be merged.
