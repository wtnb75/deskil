"""Read Claude Code session logs and split token usage by flow state interval.

Standard library only; independent of flow.py.
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")
_RUN_ID = re.compile(r"[A-Za-z0-9_-]+")

# (state id, entered at, left at); None means no upper bound.
Interval = tuple[str, datetime | None, datetime | None]


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
        parsed = parsed.astimezone()  # naive timestamps are treated as local time
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
    try:
        f = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return []
    with f:
        try:
            for line in f:
                if '"assistant"' not in line:  # cheap pre-filter before parsing
                    continue
                _add_line(turns, line, sub)
        except OSError:
            return []
    return list(turns.values())


def _add_line(turns: dict[str, Turn], line: str, sub: bool) -> None:
    """Fold one log line into `turns` (see read_turns)."""
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return
    message = entry.get("message")
    if not isinstance(message, dict):
        return
    mid, usage = message.get("id"), message.get("usage")
    if not mid or not isinstance(usage, dict):
        return
    ts = _parse_time(entry.get("timestamp"))
    if ts is None:
        return
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


def find_session_log(session_id: str, projects_dir: Path | None = None) -> Path | None:
    """Find <projects_dir>/*/<session_id>.jsonl; None if absent or id is unsafe."""
    if not _SESSION_ID.fullmatch(session_id or ""):
        return None
    if projects_dir is None:
        config = os.environ.get("CLAUDE_CONFIG_DIR")
        base = Path(config) if config else Path.home() / ".claude"
        projects_dir = base / "projects"
    return next(iter(projects_dir.glob(f"*/{session_id}.jsonl")), None)


def agent_logs(main_log: Path) -> list[Path]:
    """Subagent logs next to a main log: <id>/subagents/agent-*.jsonl, sorted."""
    return sorted((main_log.with_suffix("") / "subagents").glob("agent-*.jsonl"))


def agent_span(path: Path) -> tuple[datetime, datetime] | None:
    """Earliest and latest record timestamp of an agent log (all line types).

    Unlike the turns, this includes user lines (the prompt, tool results), so
    a one-turn agent still has a real duration. None if no line has a readable
    timestamp.
    """
    first: datetime | None = None
    last: datetime | None = None
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"timestamp"' not in line:  # cheap pre-filter before parsing
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = (
                    _parse_time(entry.get("timestamp"))
                    if isinstance(entry, dict)
                    else None
                )
                if ts is None:
                    continue
                if first is None or ts < first:
                    first = ts
                if last is None or ts > last:
                    last = ts
    except OSError:
        return None
    return (first, last) if first is not None and last is not None else None


_NAME_MAX = 60


def agent_name(log: Path) -> str:
    """Display name of a subagent: meta description, else agentType, else file stem.

    Reads agent-<id>.meta.json next to the log; a missing or invalid file just
    falls back to the stem. Long names are cut to 60 characters with an ellipsis.
    """
    meta: object = None
    try:
        meta = json.loads(
            log.with_name(f"{log.stem}.meta.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        meta = None
    name = ""
    if isinstance(meta, dict):
        for key in ("description", "agentType"):
            value = meta.get(key)
            if isinstance(value, str) and value.split():
                name = " ".join(value.split())
                break
    name = name or log.stem
    return name if len(name) <= _NAME_MAX else name[: _NAME_MAX - 1] + "…"


def intervals_of(
    history: list[dict], started_at: str, status: str, current: str
) -> list[Interval]:
    """Turn a run's history into per-state time intervals.

    Each history entry records a state and the time `at` it was left; it was
    entered when the previous entry was left (or at started_at). While the run
    is running, the current state is open-ended.
    """
    result: list[Interval] = []
    prev = _parse_time(started_at)
    for h in history:
        at = _parse_time(h.get("at"))
        # An interval with an unreadable start or end is dropped, not guessed.
        if prev is not None and at is not None:
            result.append((h["state"], prev, at))
        prev = at
    if status == "running" and prev is not None:
        result.append((current, prev, None))
    return result


def split_by_state(turns: list[Turn], intervals: list[Interval]) -> dict[str, Bucket]:
    """Sum turns into per-state buckets; entered <= ts < left."""
    buckets: dict[str, Bucket] = {}
    for turn in turns:
        for state, start, end in intervals:
            if (
                start is not None
                and start <= turn.ts
                and (end is None or turn.ts < end)
            ):
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


def timeline_intervals(
    history: list[dict], started_at: str, status: str, current: str, now: datetime
) -> list[dict]:
    """Per-visit intervals of a run, in visit order.

    Each item has state, visit (1-based count per state), start, end, gate
    (the history entry has an approval) and open. A running run's current
    state is open: end is `now`. Visits with an unreadable time are dropped
    but still count toward the visit number.
    """
    result: list[dict] = []
    seen: dict[str, int] = {}
    prev = _parse_time(started_at)
    for h in history:
        state = h["state"]
        seen[state] = seen.get(state, 0) + 1
        at = _parse_time(h.get("at"))
        if prev is not None and at is not None:
            result.append(
                {
                    "state": state,
                    "visit": seen[state],
                    "start": prev,
                    "end": at,
                    "gate": bool(h.get("approval")),
                    "open": False,
                }
            )
        prev = at
    if status == "running" and prev is not None:
        result.append(
            {
                "state": current,
                "visit": seen.get(current, 0) + 1,
                "start": prev,
                "end": now,
                "gate": False,
                "open": True,
            }
        )
    return result


def sum_turns(turns: list[Turn]) -> Bucket:
    """Sum turns into one bucket, counting turns and tool calls too."""
    bucket = Bucket()
    for turn in turns:
        bucket.add(
            Bucket(
                input=_count(turn.usage, "input_tokens"),
                cache_create=_count(turn.usage, "cache_creation_input_tokens"),
                cache_read=_count(turn.usage, "cache_read_input_tokens"),
                output=_count(turn.usage, "output_tokens"),
                turns=1,
                tool_calls=turn.tool_calls,
            )
        )
    return bucket


def _ms(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def _in_visit(turns: list[Turn], iv: dict) -> list[Turn]:
    """Turns of one visit: start <= ts < end (no upper bound while open)."""
    return [
        t for t in turns if iv["start"] <= t.ts and (iv["open"] or t.ts < iv["end"])
    ]


def build_timeline(
    *,
    history: list[dict],
    started_at: str,
    status: str,
    current: str,
    turns: list[Turn],
    agents: dict[str, list[Turn]],
    now: datetime,
    spans: dict[str, tuple[datetime, datetime]] | None = None,
    names: dict[str, str] | None = None,
) -> list[dict]:
    """Per-visit timeline with the main session and each subagent's usage.

    `agents` is keyed by agent id (log file stem). `spans` (id -> first and last
    record time of the log) gives each agent a real duration, clamped to the
    visit; without it the first and last turn in the visit are used. `names`
    maps an id to its display name (default: the id).
    """
    result = []
    for iv in timeline_intervals(history, started_at, status, current, now):
        main = sum_turns(_in_visit(turns, iv))
        agent_items = []
        for agent_id, agent_turns in agents.items():
            inside = _in_visit(agent_turns, iv)
            if not inside:
                continue
            b = sum_turns(inside)
            start = min(t.ts for t in inside)
            end = max(t.ts for t in inside)
            span = (spans or {}).get(agent_id)
            if span is not None:
                s, e = max(span[0], iv["start"]), min(span[1], iv["end"])
                if s <= e:
                    start, end = s, e
            agent_items.append(
                {
                    "name": (names or {}).get(agent_id, agent_id),
                    "id": agent_id,
                    "start": _ms(start),
                    "end": _ms(end),
                    "input": b.input,
                    "cache_create": b.cache_create,
                    "cache_read": b.cache_read,
                    "output": b.output,
                    "turns": b.turns,
                    "tool_calls": b.tool_calls,
                }
            )
        result.append(
            {
                "state": iv["state"],
                "visit": iv["visit"],
                "start": _ms(iv["start"]),
                "end": _ms(iv["end"]),
                "gate": iv["gate"],
                "open": iv["open"],
                "input": main.input,
                "cache_create": main.cache_create,
                "cache_read": main.cache_read,
                "output": main.output,
                "turns": main.turns,
                "tool_calls": main.tool_calls,
                "sub_total": sum(
                    a["input"] + a["cache_create"] + a["cache_read"] + a["output"]
                    for a in agent_items
                ),
                "agents": agent_items,
            }
        )
    return result


def timeline_from_history(
    *,
    history: list[dict],
    started_at: str,
    status: str,
    current: str,
    now: datetime,
) -> list[dict]:
    """Timeline without token data, for runs that have no session log."""
    return [
        {
            "state": iv["state"],
            "visit": iv["visit"],
            "start": _ms(iv["start"]),
            "end": _ms(iv["end"]),
            "gate": iv["gate"],
            "open": iv["open"],
            "input": None,
            "cache_create": None,
            "cache_read": None,
            "output": None,
            "turns": None,
            "tool_calls": None,
            "sub_total": None,
            "agents": [],
        }
        for iv in timeline_intervals(history, started_at, status, current, now)
    ]


def compute_usage(
    *,
    run_id: str,
    definition: str,
    definition_hash: str,
    session_id: str,
    started_at: str,
    history: list[dict],
    visits: dict[str, int],
    status: str,
    current: str,
    projects_dir: Path | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Per-state token usage of a run in the shape of usage.json.

    Also holds a per-visit `timeline`. None when the run has no session id or
    its session log cannot be found.
    """
    log = find_session_log(session_id, projects_dir)
    if log is None:
        return None
    main_turns = read_turns(log)
    sub_logs = agent_logs(log)
    turns = list(main_turns)
    for sub_log in sub_logs:
        turns += read_turns(sub_log, sub=True)
    timeline = build_timeline(
        history=history,
        started_at=started_at,
        status=status,
        current=current,
        turns=main_turns,
        agents={p.stem: read_turns(p, sub=False) for p in sub_logs},
        spans={p.stem: s for p in sub_logs if (s := agent_span(p)) is not None},
        names={p.stem: agent_name(p) for p in sub_logs},
        now=now or datetime.now().astimezone(),
    )
    buckets = split_by_state(turns, intervals_of(history, started_at, status, current))
    states = {}
    for state in sorted(set(visits) | set(buckets)):
        b = buckets.get(state, Bucket())
        states[state] = {
            "visits": visits.get(state, 0),
            "input": b.input,
            "cache_create": b.cache_create,
            "cache_read": b.cache_read,
            "output": b.output,
            "turns": b.turns,
            "tool_calls": b.tool_calls,
            "sub_total": b.sub_total,
        }
    return {
        "run_id": run_id,
        "session_id": session_id,
        "definition": definition,
        "definition_hash": definition_hash,
        "states": states,
        "timeline": timeline,
    }


def save_usage(state_dir: Path, run_id: str, data: dict) -> Path:
    """Write <state_dir>/<run_id>/usage.json (dir 0700, file 0600)."""
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError(f"invalid run id: {run_id!r}")
    run_dir = state_dir / run_id
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = run_dir / "usage.json"
    # Write a temp file in the same directory, then replace: never a partial file.
    fd, tmp = tempfile.mkstemp(dir=run_dir, prefix="usage.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def _state_total(s: dict) -> int:
    """A run's total tokens in one state, including subagents."""
    return sum(
        _count(s, k)
        for k in ("input", "cache_create", "cache_read", "output", "sub_total")
    )


def aggregate(usages: list[dict]) -> dict:
    """Aggregate per-state usage over runs.

    A run that never visited a state is left out of that state's statistics.
    """
    per_state: dict[str, list[dict]] = {}
    for u in usages:
        for state, s in (u.get("states") or {}).items():
            per_state.setdefault(state, []).append(s)
    states = {}
    for state, items in per_state.items():
        totals = [_state_total(s) for s in items]
        n = len(items)
        states[state] = {
            "runs": n,
            "visits_mean": sum(_count(s, "visits") for s in items) / n,
            "total_mean": sum(totals) / n,
            "total_min": min(totals),
            "total_max": max(totals),
            "output_mean": sum(_count(s, "output") for s in items) / n,
        }
    return {"runs": len(usages), "states": states}


def format_table(agg: dict) -> str:
    """Render an aggregate as a text table, largest mean total first."""
    header = [
        "state",
        "runs",
        "visits",
        "total(mean)",
        "min",
        "max",
        "output(mean)",
        "share",
    ]
    states = agg["states"]
    grand = sum(s["total_mean"] for s in states.values())
    rows = []
    for state, s in sorted(states.items(), key=lambda kv: -kv[1]["total_mean"]):
        share = s["total_mean"] / grand * 100 if grand else 0.0
        rows.append(
            [
                state,
                str(s["runs"]),
                f"{s['visits_mean']:.1f}",
                f"{s['total_mean']:,.0f}",
                f"{s['total_min']:,}",
                f"{s['total_max']:,}",
                f"{s['output_mean']:,.0f}",
                f"{share:.1f}%",
            ]
        )
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    lines = []
    for r in [header, *rows]:
        cells = [r[0].ljust(widths[0])]
        cells += [c.rjust(w) for c, w in zip(r[1:], widths[1:], strict=True)]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines) + "\n"


def load_usage(state_dir: Path, run_id: str) -> dict | None:
    """Read a saved usage.json; None if absent or corrupt."""
    if not _RUN_ID.fullmatch(run_id):
        return None
    try:
        data = json.loads((state_dir / run_id / "usage.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
