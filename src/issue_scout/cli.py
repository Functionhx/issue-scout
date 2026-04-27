"""Command-line entry point for issue-scout."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .claim_detector import detect_claim
from .client import GitHubClient, IssueScoutError
from .formatters import to_json, to_markdown, to_table
from .models import OutputRow

app = typer.Typer(add_completion=False, help="Find unclaimed GitHub issues.")
err_console = Console(stderr=True)

_VALID_FORMATS = {"table", "json", "md", "markdown"}


def _parse_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise typer.BadParameter("repo must be in 'owner/name' form")
    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise typer.BadParameter("repo must be in 'owner/name' form")
    return owner, name


@app.command()
def scout(
    repo: str = typer.Argument(..., help="GitHub repository, e.g. owner/name"),
    labels: list[str] = typer.Option(
        [], "--labels", "-l", help="Filter issues by label (repeatable)."
    ),
    max_issues: int = typer.Option(50, "--max-issues", "-n", help="Max issues to fetch."),
    fmt: str = typer.Option(
        "table", "--format", "-f", help="Output format: table | json | md"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write output to a file instead of stdout."
    ),
    token: Optional[str] = typer.Option(
        None, "--token", envvar="GITHUB_TOKEN", help="GitHub API token (required)."
    ),
):
    """Scan a GitHub repository for issues that nobody is working on."""
    fmt = fmt.lower()
    if fmt not in _VALID_FORMATS:
        err_console.print(f"[red]Error:[/] --format must be one of {sorted(_VALID_FORMATS)}")
        raise typer.Exit(1)

    if not token:
        err_console.print(
            "[red]Error:[/] GITHUB_TOKEN is required (GraphQL API does not accept "
            "anonymous requests).\n"
            "Create a no-permission fine-grained token at "
            "https://github.com/settings/tokens and pass it via --token "
            "or the GITHUB_TOKEN env var."
        )
        raise typer.Exit(1)

    try:
        owner, name = _parse_repo(repo)
    except typer.BadParameter as e:
        err_console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e

    client = GitHubClient(token=token)
    try:
        issues = client.fetch_issues(owner, name, labels=labels, max_issues=max_issues)
    except IssueScoutError as e:
        err_console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e

    rows: list[OutputRow] = []
    for issue in issues:
        result = detect_claim(issue)
        rows.append(
            OutputRow(
                number=issue.number,
                title=issue.title,
                url=issue.url,
                difficulty=issue.difficulty_label,
                status=result.status,
                evidence=result.evidence,
                evidence_url=result.evidence_url,
                labels=issue.labels,
            )
        )

    if fmt == "json":
        rendered = to_json(rows)
    elif fmt in ("md", "markdown"):
        rendered = to_markdown(rows)
    else:
        rendered = to_table(rows, color=None if output is None else False)

    if output:
        output.write_text(rendered, encoding="utf-8")
        err_console.print(f"[green]✓[/] wrote {len(rows)} rows to {output}")
    else:
        # to_table already printed via Console.print; avoid double-printing
        if fmt != "table":
            sys.stdout.write(rendered)
            if not rendered.endswith("\n"):
                sys.stdout.write("\n")


if __name__ == "__main__":
    app()
