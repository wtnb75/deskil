"""Tests for session-log reading and per-state interval splitting."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
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


def test_read_turns_tolerates_invalid_utf8_and_unreadable_file(tmp_path):
    good = _line("2026-01-01T00:00:01Z", "m1", _usage(o=3))
    path = tmp_path / "log.jsonl"
    path.write_bytes(b"\xff\xfe not json\n" + good.encode("utf-8") + b"\n")
    assert [t.usage["output_tokens"] for t in usage.read_turns(path)] == [3]
    assert usage.read_turns(tmp_path / "missing.jsonl") == []
    assert usage.read_turns(tmp_path) == []  # a directory: OSError


def test_unparseable_times_are_skipped_not_raised():
    history = [{"state": "a", "at": "garbage"}, {"state": "b", "at": T2}]
    got = usage.intervals_of(history, T0, "running", "c")
    assert got == [("c", _dt(T2), None)]
    assert usage.intervals_of([], "garbage", "running", "c") == []
    turns = [_turn(T1, 5)]
    assert usage.split_by_state(turns, [("a", None, None)]) == {}


def _project(tmp_path: Path, session: str, main: list[str], subs=()):
    base = tmp_path / "projects" / "proj"
    base.mkdir(parents=True)
    (base / f"{session}.jsonl").write_text("\n".join(main) + "\n", encoding="utf-8")
    if subs:
        d = base / session / "subagents"
        d.mkdir(parents=True)
        for i, lines in enumerate(subs):
            (d / f"agent-{i}.jsonl").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
    return tmp_path / "projects"


def _compute(tmp_path, session="s1", **over):
    kwargs = {
        "run_id": "r1",
        "definition": "/d/flow.toml",
        "definition_hash": "h",
        "session_id": session,
        "started_at": T0,
        "history": [{"state": "a", "at": T1}, {"state": "b", "at": T2}],
        "visits": {"a": 1, "b": 1, "e": 1},
        "status": "ended",
        "current": "e",
        "projects_dir": tmp_path / "projects",
    }
    kwargs.update(over)
    return usage.compute_usage(**kwargs)


def test_compute_usage_shape(tmp_path):
    tool = {"type": "tool_use", "name": "Bash"}
    _project(
        tmp_path,
        "s1",
        [
            _line("2026-01-01T00:05:00+00:00", "m1", _usage(i=1, o=10), [tool]),
            _line("2026-01-01T00:15:00+00:00", "m2", _usage(cc=5, cr=6, o=2)),
        ],
        subs=[[_line("2026-01-01T00:06:00+00:00", "x1", _usage(i=2, o=3))]],
    )
    got = _compute(tmp_path)
    assert got["run_id"] == "r1"
    assert got["session_id"] == "s1"
    assert got["definition"] == "/d/flow.toml"
    assert got["definition_hash"] == "h"
    assert got["states"]["a"] == {
        "visits": 1,
        "input": 1,
        "cache_create": 0,
        "cache_read": 0,
        "output": 10,
        "turns": 1,
        "tool_calls": 1,
        "sub_total": 5,
    }
    assert got["states"]["b"]["cache_create"] == 5
    assert got["states"]["b"]["cache_read"] == 6
    assert got["states"]["b"]["visits"] == 1
    assert got["states"]["e"] == {
        "visits": 1,
        "input": 0,
        "cache_create": 0,
        "cache_read": 0,
        "output": 0,
        "turns": 0,
        "tool_calls": 0,
        "sub_total": 0,
    }


def test_compute_usage_returns_none_without_session_or_log(tmp_path):
    (tmp_path / "projects").mkdir()
    assert _compute(tmp_path, session="") is None
    assert _compute(tmp_path, session="nolog") is None


def test_save_and_load_usage_roundtrip(tmp_path):
    state_dir = tmp_path / "runs"
    path = usage.save_usage(state_dir, "r1", {"run_id": "r1", "states": {}})
    assert path == state_dir / "r1" / "usage.json"
    assert (path.stat().st_mode & 0o777) == 0o600
    assert (path.parent.stat().st_mode & 0o777) == 0o700
    assert usage.load_usage(state_dir, "r1") == {"run_id": "r1", "states": {}}
    assert usage.load_usage(state_dir, "other") is None


def test_turn_just_before_a_millisecond_boundary_stays_in_the_left_state():
    # The turn that runs `next` is logged ~0.7s before the history entry's `at`.
    at = "2026-01-01T00:00:10.000+00:00"
    history = [{"state": "a", "at": at}]
    intervals = usage.intervals_of(
        history, "2026-01-01T00:00:00.000+00:00", "running", "b"
    )
    turns = [_turn("2026-01-01T00:00:09.300+00:00", 7)]
    got = usage.split_by_state(turns, intervals)
    assert got["a"].output == 7
    assert "b" not in got


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "a b", "r1\n"])
def test_save_and_load_usage_reject_bad_run_id(tmp_path, bad):
    with pytest.raises(ValueError):
        usage.save_usage(tmp_path, bad, {})
    assert usage.load_usage(tmp_path, bad) is None


def test_save_usage_is_atomic(tmp_path, monkeypatch):
    usage.save_usage(tmp_path, "r1", {"v": 1})

    def boom(src, dst):
        raise OSError("interrupted")

    monkeypatch.setattr(usage.os, "replace", boom)
    with pytest.raises(OSError):
        usage.save_usage(tmp_path, "r1", {"v": 2})
    monkeypatch.undo()
    assert usage.load_usage(tmp_path, "r1") == {"v": 1}
    assert [p.name for p in (tmp_path / "r1").iterdir()] == ["usage.json"]

    fresh = tmp_path / "fresh"
    monkeypatch.setattr(usage.os, "replace", boom)
    with pytest.raises(OSError):
        usage.save_usage(fresh, "r2", {"v": 2})
    assert list((fresh / "r2").iterdir()) == []


def test_read_turns_streams_and_skips_non_assistant_lines(tmp_path):
    good = _line("2026-01-01T00:00:01Z", "m1", _usage(o=3))
    path = _write(tmp_path, ["not json at all", '{"type": "user"}', good])
    assert [t.usage["output_tokens"] for t in usage.read_turns(path)] == [3]


def test_load_usage_returns_none_for_corrupt_file(tmp_path):
    d = tmp_path / "r1"
    d.mkdir()
    (d / "usage.json").write_text("{not json", encoding="utf-8")
    assert usage.load_usage(tmp_path, "r1") is None
    (d / "usage.json").write_text("[1]", encoding="utf-8")
    assert usage.load_usage(tmp_path, "r1") is None


def _state(visits=1, output=0, input=0, sub_total=0):
    return {
        "visits": visits,
        "input": input,
        "cache_create": 0,
        "cache_read": 0,
        "output": output,
        "turns": 1,
        "tool_calls": 0,
        "sub_total": sub_total,
    }


def test_aggregate_means_over_runs_that_visited():
    runs = [
        {"states": {"x": _state(visits=1, output=100), "y": _state(output=10)}},
        {"states": {"x": _state(visits=3, output=300), "y": _state(output=10)}},
        {"states": {"y": _state(output=10)}},
    ]
    agg = usage.aggregate(runs)
    assert agg["runs"] == 3
    x = agg["states"]["x"]
    assert x["runs"] == 2
    assert x["visits_mean"] == 2
    assert x["total_mean"] == 200
    assert (x["total_min"], x["total_max"]) == (100, 300)
    assert x["output_mean"] == 200
    assert agg["states"]["y"]["runs"] == 3


def test_aggregate_includes_sub_total():
    agg = usage.aggregate([{"states": {"x": _state(output=5, input=1, sub_total=40)}}])
    assert agg["states"]["x"]["total_mean"] == 46
    assert agg["states"]["x"]["output_mean"] == 5


def test_format_table_sorted_by_total_desc_with_share():
    agg = usage.aggregate(
        [{"states": {"small": _state(output=100), "big": _state(output=300)}}]
    )
    text = usage.format_table(agg)
    lines = text.splitlines()
    assert lines[0].split() == [
        "state",
        "runs",
        "visits",
        "total(mean)",
        "min",
        "max",
        "output(mean)",
        "share",
    ]
    assert lines[1].split()[0] == "big"
    assert lines[2].split()[0] == "small"
    assert lines[1].split()[-1] == "75.0%"
    shares = [float(ln.split()[-1].rstrip("%")) for ln in lines[1:]]
    assert abs(sum(shares) - 100.0) < 0.2
