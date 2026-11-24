"""Agent spans (all log records) and agent display names (meta.json)."""

import json

import usage
from test_timeline_data import HISTORY, _at, _compute, _iso, _kw, _log_line, _turn


def _user_line(minutes):
    return json.dumps(
        {"type": "user", "timestamp": _iso(minutes), "message": {"content": "hi"}}
    )


def test_agent_span_uses_all_timestamped_records(tmp_path):
    log = tmp_path / "agent-x.jsonl"
    log.write_text(
        "\n".join(
            [
                _user_line(4),
                "not json",
                json.dumps({"type": "user", "message": {}}),  # no timestamp
                _log_line(6, "m1", 1),
                json.dumps({"type": "user", "timestamp": "garbage"}),
                _user_line(7),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert usage.agent_span(log) == (_at(4), _at(7))


def test_agent_span_none_when_unreadable_or_empty(tmp_path):
    assert usage.agent_span(tmp_path / "missing.jsonl") is None
    empty = tmp_path / "agent-e.jsonl"
    empty.write_text("junk\n", encoding="utf-8")
    assert usage.agent_span(empty) is None


def test_build_timeline_one_turn_agent_gets_span_from_log():
    agents = {"x": [_turn(6)]}
    spans = {"x": (_at(4), _at(7))}
    tl = usage.build_timeline(**_kw(turns=[], agents=agents, spans=spans))
    ag = tl[0]["agents"][0]
    assert ag["start"] == _at(4).isoformat(timespec="milliseconds")
    assert ag["end"] == _at(7).isoformat(timespec="milliseconds")
    assert ag["turns"] == 1


def test_build_timeline_span_is_clamped_to_the_visit():
    agents = {"x": [_turn(5), _turn(12)]}
    spans = {"x": (_at(-3), _at(25))}
    a1, b1, _a2 = usage.build_timeline(**_kw(turns=[], agents=agents, spans=spans))
    assert a1["agents"][0]["start"] == _at(0).isoformat(timespec="milliseconds")
    assert a1["agents"][0]["end"] == _at(10).isoformat(timespec="milliseconds")
    assert b1["agents"][0]["start"] == _at(10).isoformat(timespec="milliseconds")
    assert b1["agents"][0]["end"] == _at(20).isoformat(timespec="milliseconds")


def test_build_timeline_open_visit_span_end_clamps_to_now():
    agents = {"x": [_turn(31)]}
    spans = {"x": (_at(30.5), _at(99))}
    tl = usage.build_timeline(
        **_kw(
            status="running",
            current="b",
            now=_at(40),
            turns=[],
            agents=agents,
            spans=spans,
        )
    )
    ag = tl[-1]["agents"][0]
    assert ag["end"] == _at(40).isoformat(timespec="milliseconds")


def test_build_timeline_without_spans_or_missing_key_keeps_turn_times():
    agents = {"x": [_turn(3), _turn(7)], "y": [_turn(5)]}
    for spans in (None, {"x": (_at(1), _at(9))}):
        tl = usage.build_timeline(**_kw(turns=[], agents=agents, spans=spans))
        y = next(a for a in tl[0]["agents"] if a["name"] == "y")
        assert y["start"] == y["end"] == _at(5).isoformat(timespec="milliseconds")
    tl = usage.build_timeline(**_kw(turns=[], agents=agents))
    x = next(a for a in tl[0]["agents"] if a["name"] == "x")
    assert x["start"] == _at(3).isoformat(timespec="milliseconds")


def test_build_timeline_names_and_ids():
    agents = {"agent-1": [_turn(2)], "agent-2": [_turn(3)]}
    names = {"agent-1": "Review", "agent-2": "Review"}
    tl = usage.build_timeline(**_kw(turns=[], agents=agents, names=names))
    got = [(a["id"], a["name"]) for a in tl[0]["agents"]]
    assert got == [("agent-1", "Review"), ("agent-2", "Review")]
    tl = usage.build_timeline(**_kw(turns=[], agents=agents))
    first = tl[0]["agents"][0]
    assert (first["id"], first["name"]) == ("agent-1", "agent-1")


def _agent_dir(tmp_path):
    _compute(tmp_path)  # writes the project tree
    return tmp_path / "projects" / "proj" / "s1" / "subagents"


def _names(tmp_path):
    got = _compute_again(tmp_path)
    return {a["id"]: a["name"] for v in got["timeline"] for a in v["agents"]}


def _compute_again(tmp_path):
    return usage.compute_usage(
        run_id="r1",
        definition="/d/flow.toml",
        definition_hash="h",
        session_id="s1",
        started_at=_iso(0),
        history=HISTORY,
        visits={"a": 2, "b": 1},
        status="ended",
        current="a",
        projects_dir=tmp_path / "projects",
        now=_at(40),
    )


def test_compute_usage_agent_name_from_meta_description(tmp_path):
    d = _agent_dir(tmp_path)
    (d / "agent-a1b2.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Re-review Task 4"}),
        encoding="utf-8",
    )
    (d / "agent-c3d4.meta.json").write_text(
        json.dumps({"agentType": "Explore", "description": "  "}), encoding="utf-8"
    )
    assert _names(tmp_path) == {
        "agent-a1b2": "Re-review Task 4",
        "agent-c3d4": "Explore",
    }


def test_compute_usage_agent_name_falls_back_to_stem(tmp_path):
    d = _agent_dir(tmp_path)
    (d / "agent-a1b2.meta.json").write_text("{not json", encoding="utf-8")
    (d / "agent-c3d4.meta.json").write_text(json.dumps(["x"]), encoding="utf-8")
    assert _names(tmp_path) == {"agent-a1b2": "agent-a1b2", "agent-c3d4": "agent-c3d4"}
    for f in d.glob("*.meta.json"):
        f.write_text(json.dumps({"description": 5, "agentType": ""}), encoding="utf-8")
    assert _names(tmp_path) == {"agent-a1b2": "agent-a1b2", "agent-c3d4": "agent-c3d4"}


def test_compute_usage_agent_name_missing_meta_and_truncation(tmp_path):
    d = _agent_dir(tmp_path)
    assert _names(tmp_path)["agent-a1b2"] == "agent-a1b2"
    (d / "agent-a1b2.meta.json").write_text(
        json.dumps({"description": "x" * 80}), encoding="utf-8"
    )
    name = _names(tmp_path)["agent-a1b2"]
    assert len(name) == 60 and name.endswith("…")


def test_compute_usage_one_turn_agent_span_includes_earlier_user_record(tmp_path):
    d = _agent_dir(tmp_path)
    (d / "agent-c3d4.jsonl").write_text(
        _user_line(13) + "\n" + _log_line(15, "y1", 7) + "\n", encoding="utf-8"
    )
    got = _compute_again(tmp_path)
    ag = got["timeline"][1]["agents"][0]
    assert ag["start"] == _at(13).isoformat(timespec="milliseconds")
    assert ag["end"] == _at(15).isoformat(timespec="milliseconds")
