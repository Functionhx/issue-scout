"""Tests for the heuristic claim detector."""
from __future__ import annotations

from issue_scout.claim_detector import detect_claim
from issue_scout.models import ClaimStatus


def test_human_assignee_is_claimed(make_issue, now):
    issue = make_issue(assignees=["carol"])
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.CLAIMED
    assert "carol" in result.evidence


def test_bot_assignee_is_not_claimed(make_issue, now):
    issue = make_issue(
        assignees=["dependabot[bot]"],
        assignee_is_bot_map={"dependabot[bot]": True},
    )
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.UNCLAIMED


def test_open_linked_pr_is_claimed(make_issue, make_pr, now):
    issue = make_issue(linked_prs=[make_pr(number=7, state="OPEN", author="dave")])
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.CLAIMED
    assert "#7" in result.evidence
    assert result.evidence_url.endswith("/pull/7")


def test_merged_pr_with_open_issue_is_resolved(make_issue, make_pr, now):
    issue = make_issue(linked_prs=[make_pr(number=8, state="MERGED")])
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.RESOLVED
    assert "#8" in result.evidence


def test_closed_unmerged_pr_does_not_resolve(make_issue, make_pr, now):
    """A PR that was closed without merging should NOT mark the issue resolved."""
    issue = make_issue(linked_prs=[make_pr(number=9, state="CLOSED")])
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.UNCLAIMED


def test_recent_claim_comment(make_issue, make_comment, now):
    issue = make_issue(comments=[make_comment("I'll take this one!", days_ago=3)])
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.CLAIMED
    assert "3d ago" in result.evidence


def test_slash_assign_command(make_issue, make_comment, now):
    issue = make_issue(comments=[make_comment("/assign", author="erin", days_ago=2)])
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.CLAIMED


def test_negation_skips_claim(make_issue, make_comment, now):
    issue = make_issue(
        comments=[
            make_comment("I'll take this but actually I can't work on it anymore", days_ago=2),
        ]
    )
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.UNCLAIMED


def test_stale_claim_becomes_likely(make_issue, make_comment, now):
    issue = make_issue(comments=[make_comment("I am working on this", days_ago=200)])
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.LIKELY_CLAIMED


def test_recent_overrides_stale(make_issue, make_comment, now):
    """Newer comments should win over older ones."""
    issue = make_issue(
        comments=[
            make_comment("I am working on it", author="old", days_ago=200),
            make_comment("I'll pick this up", author="new", days_ago=4),
        ]
    )
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.CLAIMED
    assert "@new" in result.evidence


def test_maintainer_confirm(make_issue, make_comment, now):
    issue = make_issue(
        comments=[
            make_comment("@frank feel free to send a PR!", author="maintainer", days_ago=5),
        ]
    )
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.CLAIMED
    assert "maintainer confirm" in result.evidence


def test_silence_is_unclaimed(make_issue, make_comment, now):
    issue = make_issue(
        comments=[make_comment("This is broken on my machine too.", days_ago=1)],
    )
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.UNCLAIMED


def test_bot_comment_is_ignored(make_issue, make_comment, now):
    issue = make_issue(
        comments=[
            make_comment("I'll take this", author="welcome-bot", is_bot=True, days_ago=1),
        ]
    )
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.UNCLAIMED


def test_assignee_priority_over_open_pr(make_issue, make_pr, now):
    """If both assignee and PR exist, assignee evidence wins (rule order)."""
    issue = make_issue(
        assignees=["carol"],
        linked_prs=[make_pr(state="OPEN", author="other")],
    )
    result = detect_claim(issue, now=now)
    assert result.status == ClaimStatus.CLAIMED
    assert "carol" in result.evidence
