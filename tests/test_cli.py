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


def _combined_output(result) -> str:
    """Click <8.2 mixes stderr into output; >=8.2 separates them. Handle both."""
    out = result.output or ""
    try:
        out += result.stderr or ""
    except (ValueError, AttributeError):
        pass
    return out


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
def isolated_auth(tmp_path, monkeypatch):
    """Isolate auth.json so tests never touch the real ~/.config/issue-scout."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return tmp_path


@pytest.fixture
def patched_graphql_client(monkeypatch):
    issues = [_fake_issue(1), _fake_issue(2)]
    instances: list = []

    class FakeClient:
        def __init__(self, token):
            self.token = token
            instances.append(self)

        def fetch_issues(self, owner, repo, labels=None, max_issues=50):
            return issues

    monkeypatch.setattr(cli_module, "GitHubClient", FakeClient)
    return instances


@pytest.fixture
def patched_rest_client(monkeypatch):
    instances: list = []

    class FakeRest:
        def __init__(self):
            instances.append(self)

        def fetch_issues(self, owner, repo, labels=None, max_issues=50):
            return [_fake_issue(99)]

    monkeypatch.setattr(cli_module, "AnonymousRESTClient", FakeRest)
    return instances


# ---------- scout ----------

def test_scout_with_env_token_uses_graphql(isolated_auth, patched_graphql_client, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    result = runner.invoke(app, ["scout", "o/r", "--format", "json"])
    assert result.exit_code == 0, _combined_output(result)
    assert len(patched_graphql_client) == 1
    assert patched_graphql_client[0].token == "envtok"


def test_scout_with_flag_token_overrides_env(isolated_auth, patched_graphql_client, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    result = runner.invoke(app, ["scout", "o/r", "--token", "flagtok", "--format", "json"])
    assert result.exit_code == 0
    assert patched_graphql_client[0].token == "flagtok"


def test_scout_anonymous_falls_back_to_rest(isolated_auth, patched_rest_client):
    result = runner.invoke(app, ["scout", "o/r", "--format", "json"])
    assert result.exit_code == 0, _combined_output(result)
    assert len(patched_rest_client) == 1
    out = _combined_output(result)
    assert "anonymous" in out.lower() or "anonymously" in out.lower()


def test_scout_uses_saved_token_when_no_env_or_flag(isolated_auth, patched_graphql_client):
    from issue_scout import auth as auth_mod
    auth_mod.save_token("savedtok")
    result = runner.invoke(app, ["scout", "o/r", "--format", "json"])
    assert result.exit_code == 0
    assert patched_graphql_client[0].token == "savedtok"


def test_scout_bad_repo_exits_1(isolated_auth, patched_rest_client):
    result = runner.invoke(app, ["scout", "badrepo"])
    assert result.exit_code == 1


def test_scout_invalid_format(isolated_auth, patched_rest_client):
    result = runner.invoke(app, ["scout", "o/r", "--format", "xml"])
    assert result.exit_code == 1


def test_scout_format_json(isolated_auth, patched_graphql_client, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    result = runner.invoke(app, ["scout", "o/r", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 2
    assert data[0]["status"] == "CLAIMED"


def test_scout_format_md_to_file(isolated_auth, patched_graphql_client, monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    out = tmp_path / "report.md"
    result = runner.invoke(app, ["scout", "o/r", "--format", "md", "--output", str(out)])
    assert result.exit_code == 0, _combined_output(result)
    text = out.read_text()
    assert "| --- |" in text
    assert "CLAIMED" in text
    assert "\x1b[" not in text


def test_scout_client_error_exits_1(isolated_auth, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")

    class BoomClient:
        def __init__(self, token):
            pass

        def fetch_issues(self, *a, **kw):
            raise AuthError("nope")

    monkeypatch.setattr(cli_module, "GitHubClient", BoomClient)
    result = runner.invoke(app, ["scout", "o/r"])
    assert result.exit_code == 1
    assert "nope" in _combined_output(result)


# ---------- login / logout / auth status ----------

def test_login_success(isolated_auth, monkeypatch):
    from issue_scout import auth as auth_mod
    monkeypatch.setattr(auth_mod, "device_login", lambda **kw: "gho_brandnew")
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 0, _combined_output(result)
    assert auth_mod.load_token() == "gho_brandnew"


def test_login_refuses_when_already_logged_in(isolated_auth, monkeypatch):
    from issue_scout import auth as auth_mod
    auth_mod.save_token("existing")
    called = []
    monkeypatch.setattr(auth_mod, "device_login", lambda **kw: called.append(1) or "x")
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 1
    assert called == []
    assert auth_mod.load_token() == "existing"


def test_login_force_overwrites(isolated_auth, monkeypatch):
    from issue_scout import auth as auth_mod
    auth_mod.save_token("old")
    monkeypatch.setattr(auth_mod, "device_login", lambda **kw: "new")
    result = runner.invoke(app, ["login", "--force"])
    assert result.exit_code == 0
    assert auth_mod.load_token() == "new"


def test_login_failure_exits_1(isolated_auth, monkeypatch):
    from issue_scout import auth as auth_mod

    def boom(**kw):
        raise AuthError("device flow timed out")

    monkeypatch.setattr(auth_mod, "device_login", boom)
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 1
    assert "device flow" in _combined_output(result)


def test_logout_when_present(isolated_auth):
    from issue_scout import auth as auth_mod
    auth_mod.save_token("x")
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0
    assert auth_mod.load_token() is None


def test_logout_when_absent(isolated_auth):
    result = runner.invoke(app, ["logout"])
    assert result.exit_code == 0


def test_auth_status_anonymous(isolated_auth):
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert "anonymous" in result.stdout.lower()


def test_auth_status_env(isolated_auth, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_envenvenvenv")
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert "env" in result.stdout
    # Token should be masked, not full
    assert "ghp_envenvenvenv" not in result.stdout


def test_auth_status_saved(isolated_auth):
    from issue_scout import auth as auth_mod
    auth_mod.save_token("ghs_savedsavedsaved")
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert "saved" in result.stdout
