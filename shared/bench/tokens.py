#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""tokens: sum token usage and tool errors from Claude Code session logs (jsonl).

Single file, standard library only (Python 3.11+).

Usage:
    tokens.py [--json] LABEL=FILE [LABEL=FILE ...]

Files that share a label are one group (for example `plain` and `deskil`).
The output has one row per file, then the mean of each group.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

COLUMNS = (
    "input",
    "cache_create",
    "cache_read",
    "output",
    "total",
    "turns",
    "tool_calls",
    "tool_errors",
)


@dataclass
class Stats:
    """Totals of one session."""

    input: int = 0
    cache_create: int = 0
    cache_read: int = 0
    output: int = 0
    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0

    @property
    def total(self) -> int:
        return self.input + self.cache_create + self.cache_read + self.output

    def row(self) -> list[int]:
        return [getattr(self, c) for c in COLUMNS]


def _blocks(message: dict) -> list[dict]:
    content = message.get("content")
    return (
        [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    )


def _count(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) else 0


def collect(path: Path) -> Stats:
    """Sum one session log.

    One API response can be written as several lines (one per content block)
    that all carry the same message id and usage, so usage is counted once per id.
    """
    usage_by_id: dict[str, dict] = {}
    stats = Stats()
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict):
                continue
            if entry.get("type") == "assistant":
                mid, usage = message.get("id"), message.get("usage")
                # Messages without an id (synthetic or error entries) are not API responses.
                if mid and isinstance(usage, dict):
                    # the last line of a message holds the final output count
                    usage_by_id[mid] = usage
                stats.tool_calls += sum(
                    1 for b in _blocks(message) if b.get("type") == "tool_use"
                )
            elif entry.get("type") == "user":
                stats.tool_errors += sum(
                    1
                    for b in _blocks(message)
                    if b.get("type") == "tool_result" and b.get("is_error")
                )
    stats.turns = len(usage_by_id)
    for usage in usage_by_id.values():
        stats.input += _count(usage, "input_tokens")
        stats.cache_create += _count(usage, "cache_creation_input_tokens")
        stats.cache_read += _count(usage, "cache_read_input_tokens")
        stats.output += _count(usage, "output_tokens")
    return stats


def parse_targets(targets: list[str]) -> list[tuple[str, Path]]:
    parsed = []
    for target in targets:
        label, sep, name = target.partition("=")
        if not sep or not label or not name:
            raise ValueError(f"expected LABEL=FILE, got: {target}")
        parsed.append((label, Path(name)))
    return parsed


def group_means(rows: list[tuple[str, Path, Stats]]) -> dict[str, list[float]]:
    groups: dict[str, list[Stats]] = {}
    for label, _, stats in rows:
        groups.setdefault(label, []).append(stats)
    return {
        label: [sum(col) / len(items) for col in zip(*(s.row() for s in items))]
        for label, items in groups.items()
    }


def render(rows: list[tuple[str, Path, Stats]], means: dict[str, list[float]]) -> str:
    header = ["label", "file", *COLUMNS]
    lines = [header]
    for label, path, stats in rows:
        lines.append([label, path.name, *[str(v) for v in stats.row()]])
    for label, mean in means.items():
        lines.append([f"mean:{label}", "-", *[f"{v:.1f}" for v in mean]])
    widths = [max(len(r[i]) for r in lines) for i in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(w) for cell, w in zip(r, widths)).rstrip() for r in lines
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="+", metavar="LABEL=FILE")
    parser.add_argument(
        "--json", action="store_true", help="print JSON instead of a table"
    )
    args = parser.parse_args(argv)
    try:
        targets = parse_targets(args.targets)
        rows = [(label, path, collect(path)) for label, path in targets]
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    means = group_means(rows)
    if args.json:
        out = {
            "runs": [
                {
                    "label": label,
                    "file": str(path),
                    **asdict(stats),
                    "total": stats.total,
                }
                for label, path, stats in rows
            ],
            "means": {label: dict(zip(COLUMNS, mean)) for label, mean in means.items()},
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(render(rows, means))
    return 0


if __name__ == "__main__":
    sys.exit(main())
