"""Tests for output formatters."""
from __future__ import annotations

import json

from issue_scout.formatters import to_json, to_markdown, to_table
from issue_scout.models import ClaimStatus, OutputRow

ROWS = [
    OutputRow(
        number=1,
        title="Crash on startup",
        url="https://github.com/o/r/issues/1",
        difficulty="good first issue",
        status=ClaimStatus.UNCLAIMED,
        evidence="",
        evidence_url=None,
        labels=["bug"],
    ),
    OutputRow(
        number=2,
        title="Add dark mode",
        url="https://github.com/o/r/issues/2",
        difficulty="",
        status=ClaimStatus.CLAIMED,
        evidence="@alice (3d ago): I'll take this",
        evidence_url="https://github.com/o/r/issues/2",
        labels=["feature"],
    ),
]


def test_to_json_round_trip():
    out = to_json(ROWS)
    parsed = json.loads(out)
    assert isinstance(parsed, list) and len(parsed) == 2
    assert parsed[0]["number"] == 1
    assert parsed[0]["status"] == "UNCLAIMED"
    assert parsed[1]["status"] == "CLAIMED"
    assert parsed[1]["evidence"].startswith("@alice")


def test_to_markdown_has_header_and_rows():
    out = to_markdown(ROWS)
    assert "| # | Title | Difficulty | Status | Evidence |" in out
    assert "| --- | --- | --- | --- | --- |" in out
    assert "[Crash on startup]" in out
    assert "UNCLAIMED" in out
    assert "CLAIMED" in out


def test_to_markdown_escapes_pipe_in_evidence():
    rows = [
        OutputRow(
            number=3,
            title="t",
            url="u",
            difficulty="",
            status=ClaimStatus.CLAIMED,
            evidence="weird | text",
        )
    ]
    out = to_markdown(rows)
    assert "weird \\| text" in out


def test_to_table_no_color_contains_status_text():
    out = to_table(ROWS, color=False)
    assert "Crash on startup" in out
    assert "UNCLAIMED" in out
    assert "CLAIMED" in out
    # ANSI escape sequences should be absent when color disabled
    assert "\x1b[" not in out


def test_to_table_with_color_emits_ansi():
    out = to_table(ROWS, color=True)
    assert "\x1b[" in out
