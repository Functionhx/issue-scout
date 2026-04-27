"""Tests for the CLI entry point."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

import issue_scout.cli as cli_module
from issue_scout.cli import app
from issue_scout.client import AuthError
from issue_scout.models import Comment, IssueInfo

runner = CliRunner()


def _fake_issue(number=1):
    return IssueInfo(
        number=number,
        title=f"issue {number}",
        url=f"https://github.com/o/r/issues/{number}",
        labels=["good first issue"],
        assignees=[],
        assignee_is_bot_map={},
        comments=[
            Comment(
                author_login="alice",
                author_is_bot=False,
                body="I'll take this",
                created_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
            )
        ],
        linked_prs=[],
        is_closed=False,
        repo_owner="o",
        repo_name="r",
    )


@pytest.fixture
def patched_client(monkeypatch):
    issues = [_fake_issue(1), _fake_issue(2)]

    class FakeClient:
        def __init__(self, token):
            self.token = token

        def fetch_issues(self, owner, repo, labels=None, max_issues=50):
            return issues

    monkeypatch.setattr(cli_module, "GitHubClient", FakeClient)
    return issues


def test_missing_token_exits_1(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = runner.invoke(app, ["o/r"])
    assert result.exit_code == 1
    assert "GITHUB_TOKEN" in result.stderr or "GITHUB_TOKEN" in result.output


def test_bad_repo_format_exits_1(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    result = runner.invoke(app, ["badrepo"])
    assert result.exit_code == 1


def test_format_json(monkeypatch, patched_client):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    result = runner.invoke(app, ["o/r", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert len(data) == 2
    assert data[0]["status"] == "CLAIMED"


def test_format_md_to_file(monkeypatch, patched_client, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    out = tmp_path / "report.md"
    result = runner.invoke(app, ["o/r", "--format", "md", "--output", str(out)])
    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert "| --- |" in text
    assert "CLAIMED" in text
    assert "\x1b[" not in text


def test_invalid_format(monkeypatch, patched_client):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    result = runner.invoke(app, ["o/r", "--format", "xml"])
    assert result.exit_code == 1


def test_client_error_exits_1(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")

    class BoomClient:
        def __init__(self, token):
            pass

        def fetch_issues(self, *a, **kw):
            raise AuthError("nope")

    monkeypatch.setattr(cli_module, "GitHubClient", BoomClient)
    result = runner.invoke(app, ["o/r"])
    assert result.exit_code == 1
    assert "nope" in result.stderr or "nope" in result.output
