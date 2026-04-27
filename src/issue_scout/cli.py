"""Command-line entry point for issue-scout."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import auth as auth_mod
from .claim_detector import detect_claim
from .client import AnonymousRESTClient, GitHubClient, IssueScoutError
from .formatters import to_json, to_markdown, to_table
from .models import OutputRow

app = typer.Typer(add_completion=False, help="Find unclaimed GitHub issues.")
auth_app = typer.Typer(help="Manage saved GitHub credentials.")
app.add_typer(auth_app, name="auth")
err_console = Console(stderr=True)
out_console = Console()

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
        None,
        "--token",
        envvar="GITHUB_TOKEN",
        help="GitHub API token. Falls back to saved login or anonymous mode.",
    ),
):
    """Scan a GitHub repository for issues that nobody is working on."""
    fmt = fmt.lower()
    if fmt not in _VALID_FORMATS:
        err_console.print(f"[red]Error:[/] --format must be one of {sorted(_VALID_FORMATS)}")
        raise typer.Exit(1)

    try:
        owner, name = _parse_repo(repo)
    except typer.BadParameter as e:
        err_console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e

    # typer with envvar=GITHUB_TOKEN binds the env value into `token`. Pass None
    # for env_token so we don't double-count it as both flag and env.
    resolved, source = auth_mod.resolve_credential(token, None)

    if source == "anonymous":
        err_console.print(
            "[yellow]⚠ Running anonymously via REST API "
            "(rate limit: 60 requests/hour).[/]\n"
            "  Tip: run [cyan]issue-scout login[/] (browser-based) "
            "or set [cyan]GITHUB_TOKEN[/] for the full GraphQL experience.\n"
        )
        client = AnonymousRESTClient()
    else:
        client = GitHubClient(token=resolved)

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


@app.command()
def login(
    client_id: Optional[str] = typer.Option(
        None,
        "--client-id",
        envvar="ISSUE_SCOUT_CLIENT_ID",
        help="Override the OAuth App client ID (advanced).",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing saved login without asking."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Don't try to open a browser; print the URL only."
    ),
):
    """Log in to GitHub via OAuth Device Flow and save the token locally."""
    if auth_mod.load_token() and not force:
        err_console.print(
            "[yellow]Already logged in.[/] Run [cyan]issue-scout logout[/] first, "
            "or pass [cyan]--force[/] to overwrite."
        )
        raise typer.Exit(1)
    try:
        token = auth_mod.device_login(
            client_id=client_id,
            open_browser=not no_browser,
            console=out_console,
        )
    except IssueScoutError as e:
        err_console.print(f"[red]Login failed:[/] {e}")
        raise typer.Exit(1) from e

    path = auth_mod.save_token(token)
    out_console.print(
        f"[green]✓[/] Logged in. Token saved to [cyan]{path}[/] (mode 0600)."
    )


@app.command()
def logout():
    """Forget the saved GitHub login."""
    if auth_mod.delete_token():
        out_console.print("[green]✓[/] Saved token removed.")
    else:
        out_console.print("No saved token to remove.")


@auth_app.command("status")
def auth_status():
    """Show which credential issue-scout would use right now."""
    env_tok = os.environ.get("GITHUB_TOKEN")
    resolved, source = auth_mod.resolve_credential(None, env_tok)

    out_console.print(f"Auth file: [cyan]{auth_mod.auth_file()}[/]")
    out_console.print(f"Source:    [bold]{source}[/]")
    if resolved:
        out_console.print(f"Token:     {auth_mod.mask_token(resolved)}")
    else:
        out_console.print(
            "Token:     [yellow](none — anonymous REST mode, 60 req/h)[/]"
        )


if __name__ == "__main__":
    app()
