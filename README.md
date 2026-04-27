# issue-scout

> Find open GitHub issues nobody is working on — detects claims even in comments and highlights difficulty labels.

[![CI](https://github.com/Functionhx/issue-scout/actions/workflows/ci.yml/badge.svg)](https://github.com/Functionhx/issue-scout/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

`issue-scout` is a CLI that helps you (or your AI agent) discover **truly unclaimed**
issues in any GitHub repository. Beyond the obvious `assignees` field, it scans the
last 10 comments and the linked-PR timeline with heuristic rules and classifies each
issue:

| Status            | Meaning                                                                    |
| ----------------- | -------------------------------------------------------------------------- |
| `CLAIMED`         | Has an assignee, an open linked PR, or a recent claim in comments          |
| `LIKELY_CLAIMED`  | Someone said "I'll take this" — but more than 90 days ago, no follow-up    |
| `UNCLAIMED`       | No signal anyone is working on this — go for it!                           |
| `RESOLVED`        | A linked PR was merged but the issue is still open (ping a maintainer)     |

Each non-`UNCLAIMED` row also shows the **evidence** — author, age, and a snippet of
the claim — so you can verify the heuristic.

## Install

```bash
pip install gh-issue-scout
```

Or from source:

```bash
git clone https://github.com/Functionhx/issue-scout.git
cd issue-scout
pip install -e .
```

## Authentication

A GitHub token is **required**. The GitHub GraphQL API does not accept anonymous
requests — you'll get `401 Bad credentials` without one.

1. Go to <https://github.com/settings/tokens> (or
   [fine-grained tokens](https://github.com/settings/personal-access-tokens/new)).
2. Create a token. **No permissions are required** for public repos.
3. Export it:

   ```bash
   export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
   ```

   Or pass it via `--token`.

## Quick start

Scan a repo for `good first issue` labels:

```bash
issue-scout vllm-project/vllm --labels "good first issue" --max-issues 20
```

Filter by multiple labels and write a Markdown report:

```bash
issue-scout owner/repo -l "help wanted" -l "bug" --format md --output report.md
```

Pipe JSON into `jq`:

```bash
issue-scout owner/repo --format json | jq '.[] | select(.status == "UNCLAIMED")'
```

### CLI options

```
Usage: issue-scout [OPTIONS] REPO

  Scan a GitHub repository for issues that nobody is working on.

Arguments:
  REPO                 GitHub repository, e.g. owner/name [required]

Options:
  -l, --labels TEXT    Filter issues by label (repeatable).
  -n, --max-issues INT Max issues to fetch [default: 50].
  -f, --format TEXT    Output format: table | json | md [default: table].
  -o, --output PATH    Write output to a file instead of stdout.
      --token TEXT     GitHub API token (env: GITHUB_TOKEN).
      --help           Show this message and exit.
```

### Example output (table)

```
                       issue-scout — 4 issues
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  # ┃ Title                   ┃ Difficulty        ┃ Status        ┃ Evidence                        ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 12 │ Crash on startup        │ good first issue  │ UNCLAIMED     │ -                               │
│ 18 │ Add dark mode           │ -                 │ CLAIMED       │ @alice (3d ago): I'll take this │
│ 21 │ Fix typo in README      │ good first issue  │ LIKELY_CLAIMED│ @bob (180d ago): I am working…  │
│ 33 │ Update dependency X     │ -                 │ RESOLVED      │ PR #42 merged but issue open    │
└────┴─────────────────────────┴───────────────────┴───────────────┴─────────────────────────────────┘
```

## How it works

For each open issue, `issue-scout` evaluates these rules in order and stops at
the first match:

1. Has a non-bot assignee → **CLAIMED**.
2. Has an open linked PR (via timeline `CrossReferencedEvent`) → **CLAIMED**.
3. Has a merged linked PR but the issue is still open → **RESOLVED**.
4. Recent (≤ 90 days) comment with a claim phrase ("I'll take this", `/assign`,
   "picking this up", etc.) and no negation → **CLAIMED**.
5. Maintainer-style confirmation ("@user feel free to send a PR", "all yours")
   within 90 days → **CLAIMED**.
6. Older claim phrase (> 90 days) with no follow-up → **LIKELY_CLAIMED**.
7. Otherwise → **UNCLAIMED**.

Negation phrases ("can't work on this", "dropping this", "unassign me") cause a
comment to be skipped.

## Roadmap

`issue-scout` will grow beyond the CLI:

- **Skill / MCP server** — wrap the same logic so Claude and other LLMs can call
  `find_unclaimed_issues(repo, labels)` directly with a typed JSON schema.
- **GitHub Action** — scheduled scans, posting reports as repo discussions.
- **Local cache** — JSON cache to cut API calls between runs.
- **Distribution** — PyPI first, then conda-forge & Homebrew.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setting up a conda dev environment,
running tests, and submitting PRs.

## License

MIT — see [LICENSE](LICENSE).
