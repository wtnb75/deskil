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
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
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
                problems.append(
                    Problem(
                        no + 1,
                        "item heading outside the todo / ready and done / dropped sections",
                    )
                )
            elif not m:
                problems.append(
                    Problem(
                        no + 1, "malformed item heading (expected '### B-NNN title')"
                    )
                )
            else:
                current = Item(
                    id=m.group(1),
                    title=m.group(2).strip(),
                    section=section,
                    start=no,
                    end=len(lines),
                )
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
    return [
        d
        for d in dependencies(item)
        if d not in by_id or by_id[d].get("状態") != "done"
    ]


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


def render_list(
    bl: Backlog,
    statuses: set[str] | None,
    priority: str | None = None,
    limit: int | None = None,
    exclude: set[str] | None = None,
) -> str:
    """Render the sorted list. `priority` keeps that priority or higher (items without one are dropped);
    `exclude` drops the given item ids; `limit` keeps the first N rows after sorting and filtering."""
    if priority is not None and priority not in PRIORITIES:
        raise BacklogError(
            f"invalid priority {priority!r} (use {', '.join(PRIORITIES)})"
        )
    if limit is not None and limit < 1:
        raise BacklogError(f"invalid limit {limit} (use 1 or more)")
    items = sorted_items(bl, statuses)
    if priority is not None:
        cutoff = PRIORITIES.index(priority)
        items = [
            i
            for i in items
            if i.get("優先度") in PRIORITIES
            and PRIORITIES.index(i.get("優先度")) <= cutoff
        ]
    if exclude:
        items = [i for i in items if i.id not in exclude]
    if limit is not None:
        items = items[:limit]
    rows = []
    for item in items:
        state = item.get("状態") or "-"
        row = f"{item.id}  {state}  {item.get('優先度') or '-'}  {item.title}"
        if state in DEFAULT_STATUSES:
            blockers = blocked_by(bl, item)
            if blockers:
                row += f"  [blocked by {', '.join(blockers)}]"
        rows.append(row)
    return "\n".join(rows)


def started_ids() -> set[str]:
    """Ids of items that already have a `backlog/<ID>-*` branch on origin (as of the last `git fetch --prune`;
    without `--prune`, refs of branches deleted on origin linger and keep their items hidden).
    Local-only branches are ignored on purpose: leftovers of merged or abandoned work would hide items."""
    try:
        proc = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--format=%(refname)",
                "refs/remotes/origin/backlog/",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise BacklogError(
            f"cannot read remote branches with git: {detail.strip()}"
        ) from exc
    found = (
        re.fullmatch(r"refs/remotes/origin/backlog/(B-\d+)(?:-.*)?", ref)
        for ref in proc.stdout.split()
    )
    return {m.group(1) for m in found if m}


def render_show(bl: Backlog, item_id: str) -> str:
    item = find_item(bl, item_id)
    block = bl.lines[item.start : item.end]
    while block and not block[-1].strip():
        block.pop()
    return "\n".join(block)


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

REQUIRED_KEYS = ("状態", "追加", "背景", "概要")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEPENDENCY_RE = re.compile(r"^B-\d{3,}(\s*,\s*B-\d{3,})*$")
PR_RE = re.compile(r"^#\d+$")


def _valid_date(value: str) -> bool:
    if not DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _field_line(item: Item, key: str) -> int:
    """1-based line of the first `key` field, or of the heading when the field is absent."""
    for k, _, no in item.fields:
        if k == key:
            return no + 1
    return item.start + 1


def _lint_item(item: Item) -> list[Problem]:
    problems: list[Problem] = []
    heading = item.start + 1

    seen: set[str] = set()
    for key, _, no in item.fields:
        if key in seen:
            problems.append(Problem(no + 1, f"{item.id}: duplicate field {key}"))
        seen.add(key)

    def missing(key: str) -> bool:
        return not (item.get(key) or "").strip()

    def invalid(key: str, ok: bool) -> None:
        if not ok:
            problems.append(
                Problem(
                    _field_line(item, key),
                    f"{item.id}: invalid {key} {item.get(key)!r}",
                )
            )

    required = list(REQUIRED_KEYS)
    state = item.get("状態")
    if state in ("todo", "ready"):
        required.append("優先度")
    elif state == "done":
        required.append("完了")
    if state in ("ready", "dropped"):
        required.append("判断")
    for key in required:
        if missing(key):
            problems.append(Problem(heading, f"{item.id}: missing {key}"))

    if not missing("状態"):
        invalid("状態", state in STATES)
    if not missing("優先度"):
        invalid("優先度", item.get("優先度") in PRIORITIES)
    for key in ("追加", "完了"):
        if not missing(key):
            invalid(key, _valid_date(item.get(key) or ""))
    if not missing("依存"):
        invalid("依存", bool(DEPENDENCY_RE.match(item.get("依存") or "")))
    if not missing("PR"):
        invalid("PR", bool(PR_RE.match(item.get("PR") or "")))
    if state == "dropped" and item.get("PR") is not None:
        problems.append(
            Problem(
                _field_line(item, "PR"),
                f"{item.id}: PR must not be set on a dropped item",
            )
        )

    expected = {
        "todo": SECTION_ACTIVE,
        "ready": SECTION_ACTIVE,
        "done": SECTION_ARCHIVE,
        "dropped": SECTION_ARCHIVE,
    }
    if state in expected and item.section != expected[state]:
        problems.append(
            Problem(
                _field_line(item, "状態"),
                f"{item.id}: a {state} item belongs in the '{expected[state]}' section",
            )
        )
    return problems


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Return each dependency cycle once, as a path that starts and ends at its lowest id."""
    cycles: list[list[str]] = []
    reported: set[frozenset[str]] = set()
    visited: set[str] = set()

    def walk(node: str, stack: list[str]) -> None:
        visited.add(node)
        stack.append(node)
        for nxt in graph[node]:
            if nxt in stack:
                members = stack[stack.index(nxt) :]
                if frozenset(members) not in reported:
                    reported.add(frozenset(members))
                    start = members.index(min(members))
                    rotated = members[start:] + members[:start]
                    cycles.append(rotated + [rotated[0]])
            elif nxt not in visited:
                walk(nxt, stack)
        stack.pop()

    for node in sorted(graph):
        if node not in visited:
            walk(node, [])
    return cycles


def lint(bl: Backlog) -> list[Problem]:
    """Check the backlog format and return the problems, ordered by line."""
    problems = list(bl.problems)
    first: dict[str, Item] = {}
    for item in bl.items:
        if item.id in first:
            problems.append(Problem(item.start + 1, f"duplicate item id {item.id}"))
        else:
            first[item.id] = item
        problems += _lint_item(item)

    graph: dict[str, list[str]] = {}
    for item in first.values():
        deps: list[str] = []
        if DEPENDENCY_RE.match(item.get("依存") or ""):
            for dep in dependencies(item):
                if dep in first:
                    deps.append(dep)
                else:
                    problems.append(
                        Problem(
                            _field_line(item, "依存"),
                            f"{item.id}: unknown dependency {dep}",
                        )
                    )
        graph[item.id] = deps
    for cycle in _find_cycles(graph):
        problems.append(
            Problem(
                _field_line(first[cycle[0]], "依存"),
                f"{cycle[0]}: dependency cycle {' -> '.join(cycle)}",
            )
        )
    return sorted(problems, key=lambda p: p.line)


# ---------------------------------------------------------------------------
# set / archive
# ---------------------------------------------------------------------------

SETTABLE_KEYS = ("状態", "優先度", "依存", "完了", "PR")
PLACEHOLDER = "（なし）"


def _edit_field(text: str, item_id: str, key: str, value: str) -> str:
    """Replace the `key` line of an item, or insert it after the nearest earlier field in FIELD_ORDER."""
    bl = parse(text)
    item = find_item(bl, item_id)
    lines = bl.lines
    new = f"- {key}: {value}"
    for k, _, no in item.fields:
        if k == key:
            lines[no] = new
            return "\n".join(lines)
    order = FIELD_ORDER.index(key)
    anchor = item.start
    for k, _, no in item.fields:
        if k in FIELD_ORDER and FIELD_ORDER.index(k) < order:
            anchor = max(anchor, no)
    lines.insert(anchor + 1, new)
    return "\n".join(lines)


def set_field(text: str, item_id: str, key: str, value: str) -> str:
    """Set one single-line field of an item. Every other line is left as it is."""
    if "\n" in value or "\r" in value:
        raise BacklogError("the value must not contain a newline")
    if key not in SETTABLE_KEYS:
        raise BacklogError(f"cannot set {key} (allowed: {', '.join(SETTABLE_KEYS)})")
    item = find_item(parse(text), item_id)
    if key == "優先度" and value not in PRIORITIES:
        raise BacklogError(f"invalid 優先度 {value!r} (use {', '.join(PRIORITIES)})")
    if key == "状態":
        if value in ("done", "dropped"):
            raise BacklogError(f"use 'archive {item_id}' to make an item {value}")
        if value not in ("todo", "ready"):
            raise BacklogError(f"invalid 状態 {value!r} (use todo, ready)")
        if item.section == SECTION_ARCHIVE:
            raise BacklogError(f"{item_id} is archived; its 状態 cannot be changed")
    return _edit_field(text, item_id, key, value)


def archive_item(
    text: str, item_id: str, outcome: str, pr: int | None, today: date
) -> str:
    """Mark an active item done or dropped and move its block to the end of the archive section."""
    if outcome not in ("done", "dropped"):
        raise BacklogError("the outcome must be done or dropped")
    item = find_item(parse(text), item_id)
    if item.section != SECTION_ACTIVE:
        raise BacklogError(f"{item_id} is already archived")
    if outcome == "dropped":
        if pr is not None:
            raise BacklogError("--pr is only for done items")
        if not (item.get("判断") or "").strip():
            raise BacklogError(
                f"write the 判断 of {item_id} (why it is dropped) before archiving it"
            )

    text = _edit_field(text, item_id, "状態", outcome)
    if outcome == "done":
        text = _edit_field(text, item_id, "完了", today.isoformat())
        if pr is not None:
            text = _edit_field(text, item_id, "PR", f"#{pr}")

    bl = parse(text)
    item = find_item(bl, item_id)
    lines = bl.lines
    block = lines[item.start : item.end]
    del lines[item.start : item.end]
    while block and not block[-1].strip():
        block.pop()

    try:
        head = lines.index(f"## {SECTION_ARCHIVE}")
    except ValueError:
        raise BacklogError(
            f"the '## {SECTION_ARCHIVE}' section was not found"
        ) from None
    end = next(
        (n for n in range(head + 1, len(lines)) if lines[n].startswith("## ")),
        len(lines),
    )
    for n in range(head + 1, end):
        if lines[n].strip() == PLACEHOLDER:
            del lines[n]
            end -= 1
            if n < end and not lines[n].strip():
                del lines[n]
                end -= 1
            break
    pos = end
    while pos > head + 1 and not lines[pos - 1].strip():
        pos -= 1
    tail = lines[pos:]
    lines[pos:pos] = [""] + block + ([] if tail and not tail[0].strip() else [""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def read_backlog_ref(ref: str, path: Path) -> tuple[str, Backlog]:
    """Read the backlog as committed at a git ref (e.g. `origin/main`), ignoring the working tree."""
    spec = f"{ref}:{path.as_posix()}"
    try:
        proc = subprocess.run(
            ["git", "show", spec],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise BacklogError(f"cannot read {spec} with git: {detail.strip()}") from exc
    return proc.stdout, parse(proc.stdout)


def read_backlog(path: Path) -> tuple[str, Backlog]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BacklogError(f"cannot read {path}: {exc.strerror or exc}") from exc
    return text, parse(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backlog.py", description="Read and edit the project backlog."
    )
    parser.add_argument(
        "--file", default=DEFAULT_FILE, help=f"backlog file (default: {DEFAULT_FILE})"
    )
    parser.add_argument(
        "--ref",
        help="read the backlog from this git ref (e.g. origin/main) instead of the working tree; read-only commands only",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("next-id", help="print the next free item id")

    p_list = sub.add_parser("list", help="list items by state, priority and id")
    group = p_list.add_mutually_exclusive_group()
    group.add_argument(
        "--all", action="store_true", help="include done and dropped items"
    )
    group.add_argument("--status", help="comma-separated states to show")
    p_list.add_argument(
        "--priority",
        help="show only this priority or higher (P1 to P3); items without one are hidden",
    )
    p_list.add_argument(
        "--not-started",
        action="store_true",
        help="hide items that have a backlog/<ID>-* branch on origin (run `git fetch --prune origin` first)",
    )
    p_list.add_argument(
        "--limit",
        type=int,
        help="show only the first N items (after sorting, --priority and --not-started)",
    )

    p_show = sub.add_parser("show", help="print one item")
    p_show.add_argument("id")

    sub.add_parser(
        "lint", help="check the backlog format (exit 1 when there are problems)"
    )

    p_set = sub.add_parser("set", help="set one single-line field of an item")
    p_set.add_argument("id")
    p_set.add_argument("key", help=f"one of: {', '.join(SETTABLE_KEYS)}")
    p_set.add_argument("value")

    p_archive = sub.add_parser(
        "archive", help="move an item to the done / dropped section"
    )
    p_archive.add_argument("id")
    outcome = p_archive.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--done", action="store_true")
    outcome.add_argument("--dropped", action="store_true")
    p_archive.add_argument(
        "--pr", type=int, help="pull request number (optional, only with --done)"
    )
    return parser


def write_checked(path: Path, old: str, new: str) -> None:
    """Write `new` unless it introduces a lint problem that `old` did not have."""
    known = {p.message for p in lint(parse(old))}
    added = [p.message for p in lint(parse(new)) if p.message not in known]
    if added:
        raise BacklogError(
            "refusing to write; the change would introduce: " + "; ".join(added)
        )
    try:
        path.write_text(new, encoding="utf-8")
    except OSError as exc:
        raise BacklogError(f"cannot write {path}: {exc.strerror or exc}") from exc


def run(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if args.ref:
        if args.command in ("set", "archive"):
            raise BacklogError(
                "--ref is read-only; it cannot be used with set or archive"
            )
        text, bl = read_backlog_ref(args.ref, path)
    else:
        text, bl = read_backlog(path)
    if args.command == "next-id":
        print(next_id(bl))
    elif args.command == "list":
        if args.all:
            statuses: set[str] | None = set(STATES)
        elif args.status:
            statuses = {s.strip() for s in args.status.split(",") if s.strip()}
        else:
            statuses = None
        exclude = started_ids() if args.not_started else None
        out = render_list(bl, statuses, args.priority, args.limit, exclude)
        if out:
            print(out)
    elif args.command == "show":
        print(render_show(bl, args.id))
    elif args.command == "lint":
        problems = lint(bl)
        for problem in problems:
            print(f"{args.file}:{problem.line}: {problem.message}")
        return 1 if problems else 0
    elif args.command == "set":
        write_checked(path, text, set_field(text, args.id, args.key, args.value))
    elif args.command == "archive":
        outcome = "done" if args.done else "dropped"
        write_checked(
            path, text, archive_item(text, args.id, outcome, args.pr, date.today())
        )
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
