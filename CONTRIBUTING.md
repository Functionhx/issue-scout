# Contributing to issue-scout

Thanks for your interest! This project welcomes bug reports, feature ideas, and PRs.

## Development setup

We recommend **conda** to keep your system Python clean.

```bash
# 1. Create an isolated env
conda create -n issue-scout python=3.11 -y
conda activate issue-scout

# 2. Install the package + dev dependencies
pip install -e .[dev]
```

(If you prefer `venv`, that works too: `python3.11 -m venv .venv && source .venv/bin/activate`.)

## Running tests

```bash
pytest                    # full suite + coverage gate (≥ 85%)
pytest -v --no-cov        # quick run, no coverage
pytest tests/test_claim_detector.py -v
```

All unit tests are **mock-only** (no live API calls). Real GitHub calls live in
`scripts/smoke.py`:

```bash
GITHUB_TOKEN=ghp_xxx python scripts/smoke.py vllm-project/vllm \
    --labels "good first issue" --max-issues 5

# Bypass formatters and dump raw IssueInfo:
GITHUB_TOKEN=ghp_xxx python scripts/smoke.py vllm-project/vllm --raw
```

## Linting

```bash
ruff check .              # lint
ruff check --fix .        # auto-fix safe issues
```

The same `ruff check` runs in CI.

## Project layout

```
src/issue_scout/
  models.py          dataclasses + ClaimStatus enum
  client.py          GitHubClient (GraphQL) + custom exceptions
  claim_detector.py  heuristic rules
  formatters.py      table / json / markdown
  cli.py             typer entry point
tests/               pytest suite (mocks only)
scripts/smoke.py     manual end-to-end against live API
```

## Submitting changes

1. Fork the repo and create a feature branch (`git checkout -b feat/foo`).
2. Make your change. Add or update tests — every behaviour change should have a test.
3. Ensure `ruff check .` and `pytest` are green.
4. Commit using a clear message, e.g. `feat(detector): handle "I have a PR ready" phrasing`.
5. Open a PR. Describe the motivation and reference any related issues.

## Adding new claim phrases

The patterns live in `src/issue_scout/claim_detector.py`:

- `_CLAIM_WORD` / `_CLAIM_SLASH` — claim signals
- `MAINTAINER_CONFIRM` — maintainer-style approvals
- `NEGATION` — phrases that suppress a claim

When you extend a regex, **add a unit test in `tests/test_claim_detector.py`** that
fails without your change.

## Reporting issues

When filing a bug, please include:

- Your OS and Python version
- The exact command you ran
- The full error output (with stack trace if any)
- Whether the repo you scanned is public (we can't reproduce private-repo bugs)
