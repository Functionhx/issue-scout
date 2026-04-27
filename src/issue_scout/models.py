"""Data models for issue-scout."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    LIKELY_CLAIMED = "LIKELY_CLAIMED"
    UNCLAIMED = "UNCLAIMED"
    RESOLVED = "RESOLVED"


@dataclass
class Comment:
    author_login: str
    author_is_bot: bool
    body: str
    created_at: datetime  # MUST be timezone-aware UTC


@dataclass
class LinkedPR:
    number: int
    url: str
    state: str  # one of "OPEN", "CLOSED", "MERGED"
    author_login: str


_DIFFICULTY_KEYWORDS = (
    "good first issue",
    "good-first-issue",
    "beginner",
    "easy",
    "medium",
    "hard",
    "advanced",
    "difficulty",
)


@dataclass
class IssueInfo:
    number: int
    title: str
    url: str
    labels: list[str]
    assignees: list[str]
    assignee_is_bot_map: dict[str, bool]
    comments: list[Comment]
    linked_prs: list[LinkedPR]
    is_closed: bool
    repo_owner: str
    repo_name: str

    @property
    def difficulty_label(self) -> str:
        for label in self.labels:
            low = label.lower()
            for kw in _DIFFICULTY_KEYWORDS:
                if kw in low:
                    return label
        return ""

    @property
    def human_assignees(self) -> list[str]:
        return [a for a in self.assignees if not self.assignee_is_bot_map.get(a, False)]


@dataclass
class ClaimResult:
    status: ClaimStatus
    evidence: str = ""
    evidence_url: str | None = None


@dataclass
class OutputRow:
    number: int
    title: str
    url: str
    difficulty: str
    status: ClaimStatus
    evidence: str
    evidence_url: str | None = None
    labels: list[str] = field(default_factory=list)
