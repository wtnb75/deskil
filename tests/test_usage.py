"""Tests for session-log reading and per-state interval splitting."""

import json
from datetime import UTC, datetime
from pathlib import Path

import usage

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:10:00+00:00"
T2 = "2026-01-01T00:20:00+00:00"


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _line(ts, mid, usage_dict, blocks=()):
    entry = {
        "type": "assistant",
        "message": {"content": list(blocks)},
    }
    if ts is not None:
        entry["timestamp"] = ts
    if mid is not None:
        entry["message"]["id"] = mid
    if usage_dict is not None:
        entry["message"]["usage"] = usage_dict
    return json.dumps(entry)


def _usage(i=1, cc=0, cr=0, o=1):
    return {
        "input_tokens": i,
        "cache_creation_input_tokens": cc,
        "cache_read_input_tokens": cr,
        "output_tokens": o,
    }


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "log.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_read_turns_counts_each_message_id_once(tmp_path):
    tool = {"type": "tool_use", "name": "Bash"}
    path = _write(
        tmp_path,
        [
            _line("2026-01-01T00:00:01Z", "m1", _usage(o=1), [tool]),
            _line("2026-01-01T00:00:02Z", "m1", _usage(o=9), [tool]),
        ],
    )
    turns = usage.read_turns(path)
    assert len(turns) == 1
    assert turns[0].tool_calls == 2
    assert turns[0].usage["output_tokens"] == 9
    assert turns[0].ts == datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    assert turns[0].sub is False


def test_read_turns_skips_bad_lines(tmp_path):
    path = _write(
        tmp_path,
        [
            "{not json",
            _line("2026-01-01T00:00:01Z", None, _usage()),
            _line(None, "m0", _usage()),
            _line("garbage", "m9", _usage()),
            _line("2026-01-01T00:00:02Z", "m1", _usage()),
        ],
    )
    turns = usage.read_turns(path, sub=True)
    assert [t.usage for t in turns] == [_usage()]
    assert turns[0].sub is True


def test_find_session_log_globs_projects(tmp_path, monkeypatch):
    log = tmp_path / "proj-x" / "abc-123.jsonl"
    log.parent.mkdir()
    log.write_text("", encoding="utf-8")
    assert usage.find_session_log("abc-123", tmp_path) == log
    assert usage.find_session_log("missing", tmp_path) is None
    assert usage.find_session_log("../x", tmp_path) is None

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    cfg_log = tmp_path / "cfg" / "projects" / "p" / "s1.jsonl"
    cfg_log.parent.mkdir(parents=True)
    cfg_log.write_text("", encoding="utf-8")
    assert usage.find_session_log("s1") == cfg_log

    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    home_log = tmp_path / "home" / ".claude" / "projects" / "p" / "s2.jsonl"
    home_log.parent.mkdir(parents=True)
    home_log.write_text("", encoding="utf-8")
    assert usage.find_session_log("s2") == home_log


def test_intervals_of_running_run():
    history = [{"state": "a", "at": T1}, {"state": "b", "at": T2}]
    got = usage.intervals_of(history, T0, "running", "c")
    assert got == [
        ("a", _dt(T0), _dt(T1)),
        ("b", _dt(T1), _dt(T2)),
        ("c", _dt(T2), None),
    ]


def test_intervals_of_running_run_without_history():
    assert usage.intervals_of([], T0, "running", "a") == [("a", _dt(T0), None)]


def test_intervals_of_ended_run_has_no_open_interval():
    history = [{"state": "a", "at": T1}, {"state": "b", "at": T2}]
    got = usage.intervals_of(history, T0, "ended", "b")
    assert got == [("a", _dt(T0), _dt(T1)), ("b", _dt(T1), _dt(T2))]


def _turn(ts, o, sub=False, tools=0):
    return usage.Turn(ts=_dt(ts), usage=_usage(o=o), tool_calls=tools, sub=sub)


def test_split_by_state_sums_visits_and_sub():
    intervals = [
        ("a", _dt(T0), _dt(T1)),
        ("b", _dt(T1), _dt(T2)),
        ("a", _dt(T2), None),
    ]
    turns = [
        _turn("2025-12-31T23:59:59+00:00", 100),  # before: dropped
        _turn(T0, 1, tools=1),  # inclusive start
        _turn(T1, 2),  # boundary belongs to b
        _turn("2026-01-01T00:15:00+00:00", 4, sub=True),
        _turn("2026-01-01T00:30:00+00:00", 8, tools=2),
    ]
    got = usage.split_by_state(turns, intervals)
    assert got["a"].output == 9
    assert got["a"].input == 2
    assert got["a"].turns == 2
    assert got["a"].tool_calls == 3
    assert got["b"].output == 2
    assert got["b"].turns == 1
    assert got["b"].sub_total == 5  # input 1 + output 4
    assert got["b"].total == 3
    assert got["b"].all_total == 8


def test_bucket_add():
    a = usage.Bucket(input=1, output=2, turns=1)
    a.add(usage.Bucket(input=3, cache_read=4, sub_total=5))
    assert (a.input, a.cache_read, a.output, a.turns, a.sub_total) == (4, 4, 2, 1, 5)
