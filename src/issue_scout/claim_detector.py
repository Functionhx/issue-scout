"""Heuristic claim detection for GitHub issues."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import ClaimResult, ClaimStatus, IssueInfo

STALE_DAYS = 90

_CLAIM_WORD = re.compile(
    r"\b("
    r"i(?:'| a)?m\s+(?:working\s+on|on\s+(?:it|this))"
    r"|i(?:'ll| will)\s+(?:take|work\s+on|do|tackle|handle|try|fix|pick)"
    r"|i\s+(?:want|would\s+like|can|could)\s+to\s+(?:take|work|tackle|do|look|fix)"
    r"|let\s+me\s+(?:take|do|work|try)"
    r"|assign\s+(?:me|this\s+to\s+me)"
    r"|please\s+assign\s+me"
    r"|i'?ll\s+pick\s+this\s+up"
    r"|picking\s+this\s+up"
    r"|on\s+it"
    r")\b",
    re.IGNORECASE,
)
_CLAIM_SLASH = re.compile(r"(?:^|\s)/assign(?:\s+@?\w+)?\b", re.IGNORECASE | re.MULTILINE)


class _ClaimMatcher:
    @staticmethod
    def search(text: str):
        return _CLAIM_WORD.search(text) or _CLAIM_SLASH.search(text)


CLAIM_PATTERNS = _ClaimMatcher()

MAINTAINER_CONFIRM = re.compile(
    r"@\w+[\s,.!]*("
    r"assigned"
    r"|go\s+ahead"
    r"|sounds\s+good"
    r"|sgtm"
    r"|please\s+go"
    r"|looking\s+forward\s+to\s+your\s+pr"
    r"|feel\s+free\s+to"
    r"|all\s+yours"
    r"|thanks\s+for\s+taking"
    r")",
    re.IGNORECASE,
)

NEGATION = re.compile(
    r"\b("
    r"not\s+working"
    r"|no\s+longer"
    r"|abandon(?:ed|ing)?"
    r"|gave\s+up"
    r"|can'?t\s+work"
    r"|won'?t\s+be\s+able"
    r"|unassign\s+me"
    r"|dropping\s+this"
    r"|nevermind|never\s+mind"
    r")\b",
    re.IGNORECASE,
)


def _snippet(body: str, limit: int = 140) -> str:
    body = " ".join(body.split())
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + "…"


def _evidence(comment, days_ago: int) -> str:
    return f"@{comment.author_login} ({days_ago}d ago): {_snippet(comment.body)}"


def detect_claim(issue: IssueInfo, *, now: datetime | None = None) -> ClaimResult:
    now = now or datetime.now(timezone.utc)

    # Rule 1: human assignee
    humans = issue.human_assignees
    if humans:
        return ClaimResult(
            status=ClaimStatus.CLAIMED,
            evidence=f"assigned to @{humans[0]}",
            evidence_url=issue.url,
        )

    # Rule 2/3: linked PRs
    open_pr = next((pr for pr in issue.linked_prs if pr.state == "OPEN"), None)
    if open_pr:
        return ClaimResult(
            status=ClaimStatus.CLAIMED,
            evidence=f"open PR #{open_pr.number} by @{open_pr.author_login}",
            evidence_url=open_pr.url,
        )
    merged_pr = next((pr for pr in issue.linked_prs if pr.state == "MERGED"), None)
    if merged_pr and not issue.is_closed:
        return ClaimResult(
            status=ClaimStatus.RESOLVED,
            evidence=f"PR #{merged_pr.number} merged by @{merged_pr.author_login} but issue still open",
            evidence_url=merged_pr.url,
        )

    # Rules 4–6: scan comments newest-first
    stale_evidence: ClaimResult | None = None
    for comment in sorted(issue.comments, key=lambda c: c.created_at, reverse=True):
        if comment.author_is_bot:
            continue
        body = comment.body or ""
        if NEGATION.search(body):
            continue

        days_ago = max(0, (now - comment.created_at).days)
        evidence = _evidence(comment, days_ago)

        if CLAIM_PATTERNS.search(body):
            if days_ago <= STALE_DAYS:
                return ClaimResult(
                    status=ClaimStatus.CLAIMED,
                    evidence=evidence,
                    evidence_url=issue.url,
                )
            if stale_evidence is None:
                stale_evidence = ClaimResult(
                    status=ClaimStatus.LIKELY_CLAIMED,
                    evidence=evidence,
                    evidence_url=issue.url,
                )
            continue

        if MAINTAINER_CONFIRM.search(body) and days_ago <= STALE_DAYS:
            return ClaimResult(
                status=ClaimStatus.CLAIMED,
                evidence=f"maintainer confirm — {evidence}",
                evidence_url=issue.url,
            )

    if stale_evidence is not None:
        return stale_evidence

    return ClaimResult(status=ClaimStatus.UNCLAIMED, evidence="", evidence_url=None)
