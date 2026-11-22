#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""backlog: read and edit the project backlog (docs/BACKLOG.md).

Single file, standard library only (Python 3.11+).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

STATES = ("todo", "ready", "done", "dropped")
LIST_ORDER = ("ready", "todo", "done", "dropped")  # `list` shows ready items first
PRIORITIES = ("P1", "P2", "P3")
SECTION_ACTIVE = "todo / ready"
SECTION_ARCHIVE = "done / dropped"
FIELD_ORDER = ("状態", "優先度", "依存", "追加", "背景", "概要", "判断", "完了", "PR")

DEFAULT_FILE = "docs/BACKLOG.md"
DEFAULT_STATUSES = {"todo", "ready"}

ITEM_HEADING_RE = re.compile(r"^### (B-\d{3,}) (.+)$")
FIELD_RE = re.compile(r"^- ([^:]+?):(?: (.*))?$")


class BacklogError(Exception):
    """A user-facing error. The CLI prints it without a traceback."""


@dataclass(frozen=True)
class Problem:
    """One finding. `line` is 1-based; 0 means the file as a whole."""

    line: int
    message: str


@dataclass
class Item:
    """One backlog item. `start` is its heading line, `end` the line after it (0-based)."""

    id: str
    title: str
    section: str
    start: int
    end: int
    fields: list[tuple[str, str, int]] = field(default_factory=list)

    def get(self, key: str) -> str | None:
        for k, v, _ in self.fields:
            if k == key:
                return v
        return None


@dataclass
class Backlog:
    lines: list[str]
    items: list[Item]
    problems: list[Problem]


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def parse(text: str) -> Backlog:
    """Split the backlog into items. Lines inside code fences are ignored."""
    lines = text.split("\n")
    items: list[Item] = []
    problems: list[Problem] = []
    section: str | None = None
    in_fence = False
    current: Item | None = None

    def close(end: int) -> None:
        nonlocal current
        if current is not None:
            current.end = end
            current = None

    for no, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            close(no)
            section = line[3:].strip()
            continue
        if line.startswith("### "):
            close(no)
            m = ITEM_HEADING_RE.match(line)
            if section not in (SECTION_ACTIVE, SECTION_ARCHIVE):
                problems.append(Problem(no + 1, "item heading outside the todo / ready and done / dropped sections"))
            elif not m:
                problems.append(Problem(no + 1, "malformed item heading (expected '### B-NNN title')"))
            else:
                current = Item(id=m.group(1), title=m.group(2).strip(), section=section, start=no, end=len(lines))
                items.append(current)
            continue
        if current is not None:
            m = FIELD_RE.match(line)
            if m:
                current.fields.append((m.group(1), m.group(2) or "", no))
    close(len(lines))
    return Backlog(lines=lines, items=items, problems=problems)


def find_item(bl: Backlog, item_id: str) -> Item:
    for item in bl.items:
        if item.id == item_id:
            return item
    raise BacklogError(f"unknown item: {item_id}")


def next_id(bl: Backlog) -> str:
    numbers = [int(i.id[2:]) for i in bl.items]
    return f"B-{max(numbers, default=0) + 1:03d}"


def dependencies(item: Item) -> list[str]:
    raw = item.get("依存") or ""
    return [d.strip() for d in raw.split(",") if d.strip()]


def blocked_by(bl: Backlog, item: Item) -> list[str]:
    """Dependencies that are missing or not done."""
    by_id = {i.id: i for i in bl.items}
    return [d for d in dependencies(item) if d not in by_id or by_id[d].get("状態") != "done"]


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------


def sorted_items(bl: Backlog, statuses: set[str] | None) -> list[Item]:
    wanted = DEFAULT_STATUSES if statuses is None else statuses

    def key(item: Item) -> tuple[int, int, int]:
        state = item.get("状態")
        prio = item.get("優先度")
        return (
            LIST_ORDER.index(state) if state in LIST_ORDER else len(LIST_ORDER),
            PRIORITIES.index(prio) if prio in PRIORITIES else len(PRIORITIES),
            int(item.id[2:]),
        )

    return sorted((i for i in bl.items if i.get("状態") in wanted), key=key)


def render_list(bl: Backlog, statuses: set[str] | None) -> str:
    rows = []
    for item in sorted_items(bl, statuses):
        state = item.get("状態") or "-"
        row = f"{item.id}  {state}  {item.get('優先度') or '-'}  {item.title}"
        if state in DEFAULT_STATUSES:
            blockers = blocked_by(bl, item)
            if blockers:
                row += f"  [blocked by {', '.join(blockers)}]"
        rows.append(row)
    return "\n".join(rows)


def render_show(bl: Backlog, item_id: str) -> str:
    item = find_item(bl, item_id)
    block = bl.lines[item.start : item.end]
    while block and not block[-1].strip():
        block.pop()
    return "\n".join(block)


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def read_backlog(path: Path) -> tuple[str, Backlog]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BacklogError(f"cannot read {path}: {exc.strerror or exc}") from exc
    return text, parse(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backlog.py", description="Read and edit the project backlog.")
    parser.add_argument("--file", default=DEFAULT_FILE, help=f"backlog file (default: {DEFAULT_FILE})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("next-id", help="print the next free item id")

    p_list = sub.add_parser("list", help="list items by state, priority and id")
    group = p_list.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="include done and dropped items")
    group.add_argument("--status", help="comma-separated states to show")

    p_show = sub.add_parser("show", help="print one item")
    p_show.add_argument("id")
    return parser


def run(args: argparse.Namespace) -> int:
    path = Path(args.file)
    _, bl = read_backlog(path)
    if args.command == "next-id":
        print(next_id(bl))
    elif args.command == "list":
        if args.all:
            statuses: set[str] | None = set(STATES)
        elif args.status:
            statuses = {s.strip() for s in args.status.split(",") if s.strip()}
        else:
            statuses = None
        out = render_list(bl, statuses)
        if out:
            print(out)
    elif args.command == "show":
        print(render_show(bl, args.id))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except BacklogError as exc:
        print(f"backlog: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
