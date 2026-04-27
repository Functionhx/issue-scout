"""Output formatters for issue-scout."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict

from rich.console import Console
from rich.table import Table

from .models import ClaimStatus, OutputRow

_STATUS_STYLE = {
    ClaimStatus.CLAIMED: "red",
    ClaimStatus.LIKELY_CLAIMED: "yellow",
    ClaimStatus.UNCLAIMED: "green",
    ClaimStatus.RESOLVED: "blue",
}

_STATUS_EMOJI = {
    ClaimStatus.CLAIMED: "❌",
    ClaimStatus.LIKELY_CLAIMED: "⚠️",
    ClaimStatus.UNCLAIMED: "✅",
    ClaimStatus.RESOLVED: "🟣",
}


def _truncate(text: str, limit: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def to_table(rows: list[OutputRow], *, color: bool | None = None) -> str:
    if color is None:
        color = sys.stdout.isatty()

    console = Console(
        record=True,
        force_terminal=color,
        no_color=not color,
        width=160,
    )
    table = Table(
        title=f"issue-scout — {len(rows)} issues",
        show_lines=False,
        header_style="bold",
    )
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("Difficulty", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Evidence", overflow="fold")

    for row in rows:
        style = _STATUS_STYLE.get(row.status, "")
        status_text = f"[{style}]{row.status.value}[/{style}]" if style and color else row.status.value
        table.add_row(
            str(row.number),
            _truncate(row.title, 80),
            row.difficulty or "-",
            status_text,
            _truncate(row.evidence, 100) or "-",
        )

    console.print(table)
    return console.export_text(styles=color)


def to_json(rows: list[OutputRow]) -> str:
    serializable = []
    for row in rows:
        d = asdict(row)
        d["status"] = row.status.value
        serializable.append(d)
    return json.dumps(serializable, indent=2, ensure_ascii=False)


def to_markdown(rows: list[OutputRow]) -> str:
    lines = [
        f"# issue-scout — {len(rows)} issues",
        "",
        "| # | Title | Difficulty | Status | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        emoji = _STATUS_EMOJI.get(row.status, "")
        title_md = f"[{_truncate(row.title, 80)}]({row.url})"
        evidence = _truncate(row.evidence, 120).replace("|", "\\|") or "-"
        lines.append(
            f"| {row.number} | {title_md} | {row.difficulty or '-'} "
            f"| {emoji} {row.status.value} | {evidence} |"
        )
    return "\n".join(lines) + "\n"
