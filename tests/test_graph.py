import pytest

DEF = """\
schema = 1
start = "a"

[states.a]
prompt = "Do A"

[[states.a.choices]]
label = "again"
when = "needs more work"
goto = "w"

[[states.a.choices]]
label = "stop"
when = "enough"
goto = "end"

[states.w]
prompt = "Work"
goto = "a"
max_visits = 3
on_exceed = "end"

[states.end]
prompt = "Done"
end = true
"""

EXPECTED = """\
flowchart TD
  start_node((start)) --> n_a
  n_a["a"]
  n_w["w"]
  n_end(["end"])
  n_a -->|again| n_w
  n_a -->|stop| n_end
  n_w --> n_a
  n_w -.->|max 3| n_end
"""


@pytest.fixture
def p(write_def, tmp_path):
    return write_def(tmp_path, DEF)


def test_graph_mermaid(flow, p):
    assert flow.graph_mermaid(p) == EXPECTED


def test_graph_uses_prefixed_ids_so_reserved_words_are_safe(flow, p):
    out = flow.graph_mermaid(p)
    assert "\n  end" not in out and "n_end" in out


def test_graph_rejects_a_definition_with_errors(flow, write_def, tmp_path):
    path = write_def(tmp_path, DEF.replace("[states.end]", "[states.end]\nbogus = 1"))
    with pytest.raises(flow.FlowError):
        flow.graph_mermaid(path)


def test_graph_does_not_create_state_files(flow, p, tmp_path):
    flow.graph_mermaid(p)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["flow.toml"]


def test_cli_graph(flow, p, capsys):
    assert flow.main(["graph", str(p)]) == 0
    assert capsys.readouterr().out == EXPECTED


def _stat(total, visits):
    return {
        "runs": 2,
        "visits_mean": visits,
        "total_mean": total,
        "total_min": total,
        "total_max": total,
        "output_mean": 0.0,
    }


AGG = {"runs": 2, "states": {"a": _stat(30000.0, 2.0), "w": _stat(10000.0, 1.0)}}


def test_graph_usage_labels_and_classes(flow, p):
    out = flow.graph_mermaid(p, AGG)
    assert '  n_a["a<br/>30.0k tokens<br/>2.0 visits"]\n' in out
    assert '  n_w["w<br/>10.0k tokens<br/>1.0 visits"]\n' in out
    assert '  n_end(["end"])\n' in out
    assert "  class n_a heat3\n" in out  # share 0.75 is the top of heat3
    assert "  class n_w heat1\n" in out  # share 0.25 is the top of heat1
    assert "class n_end" not in out


def test_graph_usage_classdefs_present(flow, p):
    out = flow.graph_mermaid(p, AGG)
    for i in range(1, 5):
        assert f"  classDef heat{i} fill:" in out
    assert "classDef" not in flow.graph_mermaid(p)


def test_graph_usage_steps_and_end_state_shape(flow, p):
    agg = {
        "runs": 1,
        "states": {
            "a": _stat(10.0, 1.0),
            "w": _stat(30.0, 1.0),
            "end": _stat(60.0, 1.0),
        },
    }
    out = flow.graph_mermaid(p, agg)
    assert '  n_end(["end<br/>60 tokens<br/>1.0 visits"])\n' in out
    assert "  class n_a heat1\n" in out  # 0.1
    assert "  class n_w heat2\n" in out  # 0.3
    assert "  class n_end heat3\n" in out  # 0.6


def test_graph_usage_zero_total_gets_no_class(flow, p):
    agg = {"runs": 1, "states": {"a": _stat(0.0, 1.0), "w": _stat(5.0, 1.0)}}
    out = flow.graph_mermaid(p, agg)
    assert '  n_a["a"]\n' in out
    assert "class n_a" not in out
    assert "  class n_w heat4\n" in out


def test_format_tokens(flow):
    assert flow._format_tokens(999) == "999"
    assert flow._format_tokens(1234) == "1.2k"
    assert flow._format_tokens(1234567) == "1.2M"


def test_graph_command_usage_flag(flow, p, tmp_path, capsys):
    import json

    import usage

    d = tmp_path / "state"
    d.mkdir()
    run = {
        "run_id": "r1",
        "definition": "flow.toml",
        "definition_hash": "h",
        "current": "end",
        "visits": {"a": 1},
        "history": [],
        "status": "done",
        "session_id": "s",
        "started_at": "2026-01-01T00:00:00Z",
    }
    (d / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    data = {
        "run_id": "r1",
        "states": {
            "a": {
                "visits": 1,
                "input": 10,
                "cache_create": 20,
                "cache_read": 30,
                "output": 40,
                "turns": 1,
                "tool_calls": 0,
                "sub_total": 0,
            }
        },
    }
    usage.save_usage(d, "r1", data)
    assert flow.main(["graph", str(p), "--usage", "r1", "--state-dir", str(d)]) == 0
    out = capsys.readouterr().out
    assert "classDef heat1" in out
    assert "a<br/>100 tokens<br/>1.0 visits" in out


def test_cli_graph_error_exit_1(flow, p, capsys):
    assert flow.main(["graph", str(p.with_name("nope.toml"))]) == 1
    assert "error:" in capsys.readouterr().err
