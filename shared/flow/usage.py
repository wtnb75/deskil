"""Read Claude Code session logs and split token usage by flow state interval.

Standard library only; independent of flow.py.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")

# (state id, entered at, left at); None means no upper bound.
Interval = tuple[str, datetime, datetime | None]


@dataclass
class Bucket:
    input: int = 0
    cache_create: int = 0
    cache_read: int = 0
    output: int = 0
    turns: int = 0
    tool_calls: int = 0
    sub_total: int = 0

    @property
    def total(self) -> int:
        return self.input + self.cache_create + self.cache_read + self.output

    @property
    def all_total(self) -> int:
        return self.total + self.sub_total

    def add(self, other: "Bucket") -> None:
        for name in (
            "input",
            "cache_create",
            "cache_read",
            "output",
            "turns",
            "tool_calls",
            "sub_total",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class Turn:
    ts: datetime
    usage: dict
    tool_calls: int
    sub: bool


def _parse_time(text: object) -> datetime | None:
    """Parse an ISO timestamp into an aware datetime; None if unreadable."""
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text)  # Python 3.11+ accepts a trailing Z
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _count(usage: dict, key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def read_turns(path: Path, sub: bool = False) -> list[Turn]:
    """Read one session log into turns, one per assistant message id.

    Same per-id rule as bench/tokens.py: one API response can span several
    lines (one per content block) with the same id, so usage is counted once.
    The first line's timestamp is kept and the last line's usage is used
    (it holds the final output count); tool_use blocks are summed over lines.
    """
    turns: dict[str, Turn] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "assistant":
                continue
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            mid, usage = message.get("id"), message.get("usage")
            if not mid or not isinstance(usage, dict):
                continue
            ts = _parse_time(entry.get("timestamp"))
            if ts is None:
                continue
            content = message.get("content")
            blocks = content if isinstance(content, list) else []
            tools = sum(
                1 for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"
            )
            turn = turns.get(mid)
            if turn is None:
                turns[mid] = Turn(ts=ts, usage=usage, tool_calls=tools, sub=sub)
            else:
                turn.usage = usage
                turn.tool_calls += tools
    return list(turns.values())


def find_session_log(session_id: str, projects_dir: Path | None = None) -> Path | None:
    """Find <projects_dir>/*/<session_id>.jsonl; None if absent or id is unsafe."""
    if not _SESSION_ID.fullmatch(session_id or ""):
        return None
    if projects_dir is None:
        config = os.environ.get("CLAUDE_CONFIG_DIR")
        base = Path(config) if config else Path.home() / ".claude"
        projects_dir = base / "projects"
    return next(iter(projects_dir.glob(f"*/{session_id}.jsonl")), None)


def intervals_of(
    history: list[dict], started_at: str, status: str, current: str
) -> list[Interval]:
    """Turn a run's history into per-state time intervals.

    Each history entry records a state and the time `at` it was left; it was
    entered when the previous entry was left (or at started_at). While the run
    is running, the current state is open-ended.
    """
    entries = [(h["state"], _parse_time(h["at"])) for h in history]
    result: list[Interval] = []
    prev = _parse_time(started_at)
    for state, at in entries:
        result.append((state, prev, at))
        prev = at
    if status == "running":
        result.append((current, prev, None))
    return result


def split_by_state(turns: list[Turn], intervals: list[Interval]) -> dict[str, Bucket]:
    """Sum turns into per-state buckets; entered <= ts < left."""
    buckets: dict[str, Bucket] = {}
    for turn in turns:
        for state, start, end in intervals:
            if start <= turn.ts and (end is None or turn.ts < end):
                break
        else:
            continue
        bucket = buckets.setdefault(state, Bucket())
        used = Bucket(
            input=_count(turn.usage, "input_tokens"),
            cache_create=_count(turn.usage, "cache_creation_input_tokens"),
            cache_read=_count(turn.usage, "cache_read_input_tokens"),
            output=_count(turn.usage, "output_tokens"),
        )
        if turn.sub:
            bucket.sub_total += used.total
        else:
            used.turns = 1
            used.tool_calls = turn.tool_calls
            bucket.add(used)
    return buckets
