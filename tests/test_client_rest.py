"""Tests for the anonymous REST client."""
from __future__ import annotations

import pytest
import requests

from issue_scout.client import (
    AnonymousRESTClient,
    GraphQLError,
    NetworkError,
    RateLimitError,
)


class _FakeResp:
    def __init__(self, status: int, body=None, text: str = "", headers=None):
        self.status_code = status
        self._body = body if body is not None else []
        self.text = text or ""
        self.headers = headers or {}

    def json(self):
        return self._body


def _route(responses_by_path):
    """Return a fake .get(url, params, timeout) honoring path -> [responses]."""

    def fake_get(self, url, params=None, timeout=None):
        for path_suffix, queue in responses_by_path.items():
            if url.endswith(path_suffix):
                return queue.pop(0)
        raise AssertionError(f"unexpected URL: {url}")

    return fake_get


def test_fetch_filters_pull_requests(monkeypatch):
    issues_page = [
        {
            "number": 1,
            "title": "real issue",
            "html_url": "u1",
            "labels": [{"name": "bug"}],
            "assignees": [],
            "state": "open",
        },
        {
            "number": 2,
            "title": "actually a PR",
            "html_url": "u2",
            "labels": [],
            "assignees": [],
            "state": "open",
            "pull_request": {"html_url": "pr2"},
        },
    ]
    responses = {
        "/issues": [_FakeResp(200, issues_page)],
        "/issues/1/comments": [_FakeResp(200, [])],
        "/issues/1/timeline": [_FakeResp(200, [])],
    }
    monkeypatch.setattr(requests.Session, "get", _route(responses), raising=False)

    client = AnonymousRESTClient()
    issues = client.fetch_issues("o", "r", max_issues=10)
    assert len(issues) == 1
    assert issues[0].number == 1
    assert issues[0].labels == ["bug"]


def test_fetch_assembles_comments_and_open_pr(monkeypatch):
    responses = {
        "/issues": [
            _FakeResp(200, [{
                "number": 7, "title": "t", "html_url": "u",
                "labels": [], "assignees": [{"login": "carol", "type": "User"}],
                "state": "open",
            }])
        ],
        "/issues/7/comments": [
            _FakeResp(200, [{
                "user": {"login": "alice", "type": "User"},
                "body": "I'll take this",
                "created_at": "2026-04-25T10:00:00Z",
            }])
        ],
        "/issues/7/timeline": [
            _FakeResp(200, [{
                "event": "cross-referenced",
                "source": {"issue": {
                    "number": 99,
                    "html_url": "https://gh/o/r/issues/99",
                    "pull_request": {"html_url": "https://gh/o/r/pull/99"},
                    "state": "open",
                    "user": {"login": "dave"},
                }},
            }])
        ],
    }
    monkeypatch.setattr(requests.Session, "get", _route(responses), raising=False)

    client = AnonymousRESTClient()
    issues = client.fetch_issues("o", "r", max_issues=5)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.assignees == ["carol"]
    assert issue.assignee_is_bot_map == {"carol": False}
    assert len(issue.comments) == 1
    assert issue.comments[0].body == "I'll take this"
    assert len(issue.linked_prs) == 1
    assert issue.linked_prs[0].number == 99
    assert issue.linked_prs[0].state == "OPEN"


def test_fetch_classifies_merged_pr(monkeypatch):
    responses = {
        "/issues": [
            _FakeResp(200, [{
                "number": 8, "title": "t", "html_url": "u",
                "labels": [], "assignees": [], "state": "open",
            }])
        ],
        "/issues/8/comments": [_FakeResp(200, [])],
        "/issues/8/timeline": [
            _FakeResp(200, [{
                "event": "cross-referenced",
                "source": {"issue": {
                    "number": 42,
                    "html_url": "https://gh/o/r/issues/42",
                    "pull_request": {"html_url": "https://gh/o/r/pull/42"},
                    "state": "closed",
                    "user": {"login": "x"},
                }},
            }])
        ],
        "/pulls/42": [_FakeResp(200, {"merged": True})],
    }
    monkeypatch.setattr(requests.Session, "get", _route(responses), raising=False)

    client = AnonymousRESTClient()
    issues = client.fetch_issues("o", "r", max_issues=5)
    assert issues[0].linked_prs[0].state == "MERGED"


def test_rate_limit_raises(monkeypatch):
    responses = {
        "/issues": [_FakeResp(403, [], text="API rate limit exceeded",
                              headers={"X-RateLimit-Remaining": "0"})],
    }
    monkeypatch.setattr(requests.Session, "get", _route(responses), raising=False)

    client = AnonymousRESTClient()
    with pytest.raises(RateLimitError):
        client.fetch_issues("o", "r", max_issues=5)


def test_404_raises_graphql_error(monkeypatch):
    responses = {"/issues": [_FakeResp(404, {})]}
    monkeypatch.setattr(requests.Session, "get", _route(responses), raising=False)

    client = AnonymousRESTClient()
    with pytest.raises(GraphQLError):
        client.fetch_issues("o", "r", max_issues=5)


def test_network_error(monkeypatch):
    def boom(self, url, params=None, timeout=None):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests.Session, "get", boom, raising=False)
    client = AnonymousRESTClient()
    with pytest.raises(NetworkError):
        client.fetch_issues("o", "r", max_issues=5)
