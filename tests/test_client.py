"""Tests for GitHubClient — uses monkeypatched requests.Session."""
from __future__ import annotations

from typing import Any

import pytest
import requests

from issue_scout.client import (
    AuthError,
    GitHubClient,
    GraphQLError,
    NetworkError,
    RateLimitError,
)


class _FakeResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or ""

    def json(self):
        return self._json


def _make_issue_node(number: int) -> dict:
    return {
        "number": number,
        "title": f"issue {number}",
        "url": f"https://github.com/o/r/issues/{number}",
        "labels": {"nodes": [{"name": "good first issue"}]},
        "assignees": {"nodes": []},
        "comments": {"nodes": []},
        "timelineItems": {"nodes": []},
    }


def _wrap(nodes, has_next=False, end_cursor=None):
    return {
        "data": {
            "repository": {
                "issues": {
                    "nodes": nodes,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                }
            }
        }
    }


def test_fetch_paginates_and_caps(monkeypatch):
    page1 = _wrap([_make_issue_node(i) for i in [10, 9, 8]], has_next=True, end_cursor="cur1")
    page2 = _wrap([_make_issue_node(i) for i in [7, 6, 5]], has_next=False)
    responses = [page1, page2]
    calls: list[dict] = []

    def fake_post(self, url, json=None, timeout=None):
        calls.append(json)
        return _FakeResponse(200, responses.pop(0))

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    client = GitHubClient(token="dummy")
    issues = client.fetch_issues("o", "r", max_issues=4)
    assert [i.number for i in issues] == [10, 9, 8, 7]
    assert len(calls) == 2
    # second page should pass cursor from first
    assert calls[1]["variables"]["cursor"] == "cur1"


def test_labels_variable_only_when_provided(monkeypatch):
    seen: list[dict] = []

    def fake_post(self, url, json=None, timeout=None):
        seen.append(json)
        return _FakeResponse(200, _wrap([], has_next=False))

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    client = GitHubClient(token="dummy")
    client.fetch_issues("o", "r", labels=["bug", "help wanted"], max_issues=10)
    assert seen[0]["variables"]["labels"] == ["bug", "help wanted"]
    assert "$labels" in seen[0]["query"]

    seen.clear()
    client.fetch_issues("o", "r", labels=None, max_issues=10)
    assert "labels" not in seen[0]["variables"]
    assert "$labels" not in seen[0]["query"]


def test_401_raises_auth_error(monkeypatch):
    def fake_post(self, url, json=None, timeout=None):
        return _FakeResponse(401, text="Bad credentials")

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    client = GitHubClient(token="bad")
    with pytest.raises(AuthError):
        client.fetch_issues("o", "r")


def test_403_rate_limit(monkeypatch):
    def fake_post(self, url, json=None, timeout=None):
        return _FakeResponse(403, text="API rate limit exceeded for user")

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    client = GitHubClient(token="x")
    with pytest.raises(RateLimitError):
        client.fetch_issues("o", "r")


def test_graphql_errors_field(monkeypatch):
    def fake_post(self, url, json=None, timeout=None):
        return _FakeResponse(200, {"errors": [{"message": "bad query"}]})

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    client = GitHubClient(token="x")
    with pytest.raises(GraphQLError):
        client.fetch_issues("o", "r")


def test_network_error(monkeypatch):
    def fake_post(self, url, json=None, timeout=None):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    client = GitHubClient(token="x")
    with pytest.raises(NetworkError):
        client.fetch_issues("o", "r")


def test_repo_not_found(monkeypatch):
    def fake_post(self, url, json=None, timeout=None):
        return _FakeResponse(200, {"data": {"repository": None}})

    monkeypatch.setattr(requests.Session, "post", fake_post, raising=False)
    client = GitHubClient(token="x")
    with pytest.raises(GraphQLError):
        client.fetch_issues("o", "r")


def test_node_to_issue_parses_assignees_comments_prs(monkeypatch):
    node = {
        "number": 1,
        "title": "t",
        "url": "u",
        "labels": {"nodes": [{"name": "bug"}]},
        "assignees": {"nodes": [{"login": "carol"}, {"login": "dependabot[bot]"}]},
        "comments": {
            "nodes": [
                {
                    "author": {"login": "alice", "__typename": "User"},
                    "bodyText": "hi",
                    "createdAt": "2026-01-01T00:00:00Z",
                }
            ]
        },
        "timelineItems": {
            "nodes": [
                {
                    "__typename": "CrossReferencedEvent",
                    "source": {
                        "__typename": "PullRequest",
                        "number": 5,
                        "url": "pr-url",
                        "state": "OPEN",
                        "author": {"login": "dave"},
                    },
                }
            ]
        },
    }
    issue = GitHubClient._node_to_issue(node, "o", "r")
    assert issue.assignees == ["carol", "dependabot[bot]"]
    assert issue.assignee_is_bot_map == {"carol": False, "dependabot[bot]": True}
    assert issue.human_assignees == ["carol"]
    assert issue.linked_prs[0].number == 5
    assert issue.comments[0].author_login == "alice"
