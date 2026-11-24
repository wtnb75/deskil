"""Tests for the per-visit timeline (with per-subagent usage)."""

from datetime import UTC, datetime, timedelta

import usage

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def _at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _iso(minutes: float) -> str:
    return _at(minutes).isoformat()


def _turn(minutes, i=1, o=1, tools=0, cc=0, cr=0, sub=False):
    return usage.Turn(
        ts=_at(minutes),
        usage={
            "input_tokens": i,
            "cache_creation_input_tokens": cc,
            "cache_read_input_tokens": cr,
            "output_tokens": o,
        },
        tool_calls=tools,
        sub=sub,
    )


# a(0-10) -> b(10-20, gated) -> a(20-30) ; ended
HISTORY = [
    {"state": "a", "at": _iso(10)},
    {"state": "b", "at": _iso(20), "approval": "ok"},
    {"state": "a", "at": _iso(30)},
]


def _kw(**over):
    base = {
        "history": HISTORY,
        "started_at": _iso(0),
        "status": "ended",
        "current": "end",
        "now": _at(60),
    }
    base.update(over)
    return base


def test_timeline_intervals_marks_gate_and_visit_numbers():
    rows = usage.timeline_intervals(HISTORY, _iso(0), "ended", "end", _at(60))
    assert [(r["state"], r["visit"], r["gate"], r["open"]) for r in rows] == [
        ("a", 1, False, False),
        ("b", 1, True, False),
        ("a", 2, False, False),
    ]
    assert rows[0]["start"] == _at(0)
    assert rows[0]["end"] == _at(10)


def test_timeline_intervals_open_state_ends_now():
    rows = usage.timeline_intervals(HISTORY, _iso(0), "running", "b", _at(45))
    last = rows[-1]
    assert (last["state"], last["visit"], last["open"]) == ("b", 2, True)
    assert last["start"] == _at(30)
    assert last["end"] == _at(45)
    ended = usage.timeline_intervals(HISTORY, _iso(0), "ended", "b", _at(45))
    assert len(ended) == 3
    assert not any(r["open"] for r in ended)


def test_timeline_intervals_drops_unreadable_times_and_empty_started_at():
    rows = usage.timeline_intervals(HISTORY, "", "ended", "end", _at(60))
    assert [(r["state"], r["start"]) for r in rows] == [
        ("b", _at(10)),
        ("a", _at(20)),
    ]


def test_build_timeline_splits_main_turns_per_visit():
    turns = [
        _turn(1, i=1, o=2, tools=1),
        _turn(10, i=10, o=20, tools=2),  # ts == end of visit 1 -> next visit
        _turn(15, i=100, o=200, cc=5, cr=7, tools=3),
    ]
    tl = usage.build_timeline(**_kw(turns=turns, agents={}))
    a1, b1, a2 = tl
    assert (a1["input"], a1["output"], a1["turns"], a1["tool_calls"]) == (1, 2, 1, 1)
    assert (b1["input"], b1["output"], b1["turns"], b1["tool_calls"]) == (
        110,
        220,
        2,
        5,
    )
    assert (b1["cache_create"], b1["cache_read"]) == (5, 7)
    assert a2["turns"] == 0
    assert a1["start"] == _at(0).isoformat(timespec="milliseconds")
    assert a1["end"] == _at(10).isoformat(timespec="milliseconds")
    assert b1["gate"] is True and a1["open"] is False
    assert set(a1) == {
        "state",
        "visit",
        "start",
        "end",
        "gate",
        "open",
        "input",
        "cache_create",
        "cache_read",
        "output",
        "turns",
        "tool_calls",
        "sub_total",
        "agents",
    }


def test_build_timeline_agent_spanning_two_visits_is_split():
    agents = {"x": [_turn(5, i=1, o=1), _turn(12, i=2, o=3, tools=1)]}
    tl = usage.build_timeline(**_kw(turns=[], agents=agents))
    a1, b1, _a2 = tl
    assert len(a1["agents"]) == 1 and len(b1["agents"]) == 1
    assert a1["agents"][0]["name"] == "x"
    assert a1["agents"][0]["output"] == 1
    assert b1["agents"][0]["output"] == 3
    assert b1["agents"][0]["tool_calls"] == 1
    assert a1["sub_total"] == 2
    assert b1["sub_total"] == 5
    assert set(a1["agents"][0]) == {
        "name",
        "start",
        "end",
        "input",
        "cache_create",
        "cache_read",
        "output",
        "turns",
        "tool_calls",
    }


def test_build_timeline_agent_start_end_are_first_and_last_turn_in_visit():
    agents = {"x": [_turn(3), _turn(7), _turn(9.5), _turn(11)]}
    tl = usage.build_timeline(**_kw(turns=[], agents=agents))
    ag = tl[0]["agents"][0]
    assert ag["start"] == _at(3).isoformat(timespec="milliseconds")
    assert ag["end"] == _at(9.5).isoformat(timespec="milliseconds")
    assert ag["turns"] == 3


def test_build_timeline_omits_agents_without_turns_in_a_visit():
    agents = {"x": [_turn(5)], "y": [_turn(15)]}
    tl = usage.build_timeline(**_kw(turns=[], agents=agents))
    assert [a["name"] for a in tl[0]["agents"]] == ["x"]
    assert [a["name"] for a in tl[1]["agents"]] == ["y"]
    assert tl[2]["agents"] == []


def test_build_timeline_open_visit_has_no_upper_bound_for_turns():
    tl = usage.build_timeline(
        **_kw(
            status="running",
            current="b",
            now=_at(40),
            turns=[_turn(50, o=9)],
            agents={"x": [_turn(55, o=4)]},
        )
    )
    last = tl[-1]
    assert last["open"] is True
    assert last["end"] == _at(40).isoformat(timespec="milliseconds")
    assert last["output"] == 9
    assert last["agents"][0]["output"] == 4


def test_timeline_from_history_has_none_tokens():
    tl = usage.timeline_from_history(**_kw())
    assert len(tl) == 3
    assert tl[1]["gate"] is True
    assert tl[1]["start"] == _at(10).isoformat(timespec="milliseconds")
    for row in tl:
        for key in (
            "input",
            "cache_create",
            "cache_read",
            "output",
            "turns",
            "tool_calls",
            "sub_total",
        ):
            assert row[key] is None
        assert row["agents"] == []
