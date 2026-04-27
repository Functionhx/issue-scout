"""Manual smoke test against the live GitHub GraphQL API.

Usage:
    GITHUB_TOKEN=ghp_xxx python scripts/smoke.py owner/repo \\
        --labels "good first issue" --max-issues 5

With --raw, prints the parsed IssueInfo objects directly (skips claim detection
and formatters), which is handy for debugging the GraphQL query / parsing.

Otherwise, invokes the full CLI through typer.testing.CliRunner so this exercises
the same code path users hit.
"""
from __future__ import annotations

import argparse
import os
import sys


def _run_raw(repo: str, labels: list[str], max_issues: int) -> int:
    from issue_scout.client import GitHubClient, IssueScoutError

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN env var required", file=sys.stderr)
        return 1
    owner, name = repo.split("/", 1)
    client = GitHubClient(token=token)
    try:
        issues = client.fetch_issues(owner, name, labels=labels, max_issues=max_issues)
    except IssueScoutError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for i in issues:
        print(f"#{i.number} {i.title}")
        print(f"  url={i.url}")
        print(f"  labels={i.labels}")
        print(f"  assignees={i.assignees} bots={i.assignee_is_bot_map}")
        print(f"  comments={len(i.comments)} linked_prs={[(p.number, p.state) for p in i.linked_prs]}")
        for c in i.comments[-3:]:
            snippet = c.body[:80].replace("\n", " ")
            print(f"    [{c.created_at.date()}] @{c.author_login}: {snippet}")
        print()
    print(f"Fetched {len(issues)} issues.")
    return 0


def _run_cli(repo: str, labels: list[str], max_issues: int, fmt: str, token: str | None) -> int:
    from typer.testing import CliRunner

    from issue_scout.cli import app

    args: list[str] = [repo, "--max-issues", str(max_issues), "--format", fmt]
    for label in labels:
        args.extend(["--labels", label])
    if token:
        args.extend(["--token", token])

    runner = CliRunner()
    result = runner.invoke(app, args)
    sys.stdout.write(result.stdout)
    if result.stderr_bytes:
        sys.stderr.write(result.stderr)
    print(f"\n[smoke] exit_code={result.exit_code}", file=sys.stderr)
    return result.exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test for issue-scout.")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--labels", action="append", default=[])
    parser.add_argument("--max-issues", type=int, default=5)
    parser.add_argument("--format", default="table", choices=["table", "json", "md"])
    parser.add_argument("--raw", action="store_true", help="Bypass CLI; dump raw IssueInfo")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token (defaults to $GITHUB_TOKEN).",
    )
    args = parser.parse_args()

    if args.token:
        os.environ["GITHUB_TOKEN"] = args.token

    if args.raw:
        return _run_raw(args.repo, args.labels, args.max_issues)
    return _run_cli(args.repo, args.labels, args.max_issues, args.format, args.token)


if __name__ == "__main__":
    raise SystemExit(main())
