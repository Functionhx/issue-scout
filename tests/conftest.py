"""Test fixtures for issue-scout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from issue_scout.models import Comment, IssueInfo, LinkedPR

NOW = datetime(2026, 4, 27, 12, 0, 0, tzinfo=timezone.utc)


def _make_comment(
    body: str,
    *,
    author: str = "alice",
    is_bot: bool = False,
    days_ago: int = 1,
) -> Comment:
    return Comment(
        author_login=author,
        author_is_bot=is_bot,
        body=body,
        created_at=NOW - timedelta(days=days_ago),
    )


def _make_pr(
    number: int = 1,
    *,
    state: str = "OPEN",
    author: str = "bob",
) -> LinkedPR:
    return LinkedPR(
        number=number,
        url=f"https://github.com/o/r/pull/{number}",
        state=state,
        author_login=author,
    )


def _make_issue(
    *,
    number: int = 42,
    title: str = "Some bug",
    labels: list[str] | None = None,
    assignees: list[str] | None = None,
    assignee_is_bot_map: dict[str, bool] | None = None,
    comments: list[Comment] | None = None,
    linked_prs: list[LinkedPR] | None = None,
    is_closed: bool = False,
) -> IssueInfo:
    assignees = assignees or []
    return IssueInfo(
        number=number,
        title=title,
        url=f"https://github.com/o/r/issues/{number}",
        labels=labels or [],
        assignees=assignees,
        assignee_is_bot_map=assignee_is_bot_map or {a: False for a in assignees},
        comments=comments or [],
        linked_prs=linked_prs or [],
        is_closed=is_closed,
        repo_owner="o",
        repo_name="r",
    )


@pytest.fixture
def make_comment():
    return _make_comment


@pytest.fixture
def make_pr():
    return _make_pr


@pytest.fixture
def make_issue():
    return _make_issue


@pytest.fixture
def now():
    return NOW
