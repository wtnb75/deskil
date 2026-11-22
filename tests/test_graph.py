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


def test_cli_graph_error_exit_1(flow, p, capsys):
    assert flow.main(["graph", str(p.with_name("nope.toml"))]) == 1
    assert "error:" in capsys.readouterr().err
