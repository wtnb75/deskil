import tomllib

import pytest


def defn(states: dict[str, str], extra: str = "", start: str = "a") -> str:
    """Build a definition from {state id: body}."""
    parts = [f'schema = 1\nstart = "{start}"\n{extra}']
    for sid, body in states.items():
        parts.append(f'[states.{sid}]\nprompt = "{sid}"\n{body}')
    return "\n".join(parts)


END = "end = true\n"


def graph(flow, text):
    return flow.lint_graph(tomllib.loads(text))


def codes(issues):
    return {i.code for i in issues}


def test_clean_definition_has_no_issues(flow):
    assert graph(flow, defn({"a": 'goto = "b"\n', "b": END})) == []


def test_orphan(flow):
    issues = graph(flow, defn({"a": 'goto = "b"\n', "b": END, "s9": 'goto = "b"\n'}))
    orphans = [i for i in issues if i.code == "orphan"]
    assert len(orphans) == 1 and orphans[0].level == "error"
    assert "states.s9" in orphans[0].where


def test_dead_end_cycle(flow):
    issues = graph(flow, defn({"a": 'goto = "b"\n', "b": 'goto = "a"\n'}))
    dead = [i for i in issues if i.code == "dead-end"]
    assert {i.where for i in dead} == {"states.a", "states.b"}
    assert all(i.level == "error" for i in dead)


BOUNDED = defn(
    {
        "a": 'goto = "b"\n',
        "b": 'goto = "a"\nmax_visits = 2\non_exceed = "c"\n',
        "c": END,
    }
)


def test_dead_end_via_on_exceed_is_ok(flow):
    assert "dead-end" not in codes(graph(flow, BOUNDED))


def test_bounded_loop_no_warning(flow):
    assert "unbounded-loop" not in codes(graph(flow, BOUNDED))


def test_unbounded_loop_warning(flow):
    text = defn(
        {
            "a": (
                '[[states.a.choices]]\nlabel = "again"\nwhen = "w"\ngoto = "a"\n'
                '[[states.a.choices]]\nlabel = "done"\nwhen = "w"\ngoto = "c"\n'
            ),
            "c": END,
        }
    )
    issues = graph(flow, text)
    loops = [i for i in issues if i.code == "unbounded-loop"]
    assert len(loops) == 1 and loops[0].level == "warning"
    assert not [i for i in issues if i.level == "error"]


def test_unused_note_warning(flow):
    text = defn(
        {"a": 'goto = "b"\nnotes = ["used"]\n', "b": END},
        extra='[notes.common]\nused = "u"\nunused = "x"\n',
    )
    # [notes.common] must precede [states.*]; defn puts extra right after the top keys.
    issues = graph(flow, text)
    unused = [i for i in issues if i.code == "unused-note"]
    assert len(unused) == 1 and unused[0].level == "warning"
    assert "unused" in unused[0].where


def test_single_choice_warning(flow):
    text = defn(
        {
            "a": '[[states.a.choices]]\nlabel = "x"\nwhen = "w"\ngoto = "b"\n',
            "b": END,
        }
    )
    issues = graph(flow, text)
    assert [i.level for i in issues if i.code == "single-choice"] == ["warning"]


def test_lint_skips_graph_when_schema_errors(flow, write_def, tmp_path):
    text = defn({"a": 'goto = "b"\nbogus = 1\n', "b": END, "s9": 'goto = "b"\n'})
    issues = flow.lint(write_def(tmp_path, text))
    assert "unknown-key" in codes(issues)
    assert "orphan" not in codes(issues)


def test_lint_runs_graph_when_schema_ok(flow, write_def, tmp_path):
    text = defn({"a": 'goto = "b"\n', "b": END, "s9": 'goto = "b"\n'})
    assert "orphan" in codes(flow.lint(write_def(tmp_path, text)))


def test_lint_resolves_files_relative_to_definition(flow, write_def, tmp_path):
    (tmp_path / "p.md").write_text("body", encoding="utf-8")
    text = defn({"a": 'goto = "b"\n', "b": END}).replace(
        'prompt = "a"', 'prompt = { file = "p.md" }'
    )
    assert flow.lint(write_def(tmp_path, text)) == []


def test_lint_returns_toml_error(flow, write_def, tmp_path):
    with pytest.raises(flow.FlowError):
        flow.lint(write_def(tmp_path, "start = \n"))


def test_on_exceed_only_cycle_is_an_error(flow):
    issues = graph(
        flow,
        defn(
            {
                "a": 'goto = "b"\n',
                "b": 'goto = "e"\nmax_visits = 1\non_exceed = "c"\n',
                "c": 'goto = "e"\nmax_visits = 1\non_exceed = "b"\n',
                "e": END,
            }
        ),
    )
    cyc = [i for i in issues if i.code == "on-exceed-cycle"]
    assert len(cyc) == 1 and cyc[0].level == "error" and "states.b" in cyc[0].where


def test_on_exceed_self_loop_is_an_error(flow):
    issues = graph(
        flow,
        defn(
            {
                "a": 'goto = "b"\n',
                "b": 'goto = "e"\nmax_visits = 1\non_exceed = "b"\n',
                "e": END,
            }
        ),
    )
    assert "on-exceed-cycle" in codes(issues)


def test_on_exceed_chain_without_cycle_is_fine(flow):
    issues = graph(
        flow,
        defn(
            {
                "a": 'goto = "b"\n',
                "b": 'goto = "e"\nmax_visits = 1\non_exceed = "c"\n',
                "c": 'goto = "e"\nmax_visits = 1\non_exceed = "e"\n',
                "e": END,
            }
        ),
    )
    assert "on-exceed-cycle" not in codes(issues)


def test_cycle_through_a_normal_edge_is_not_an_on_exceed_cycle(flow):
    issues = graph(
        flow,
        defn(
            {
                "a": 'goto = "b"\n',
                "b": 'goto = "c"\nmax_visits = 2\non_exceed = "e"\n',
                "c": 'goto = "b"\n',
                "e": END,
            }
        ),
    )
    assert "on-exceed-cycle" not in codes(issues)
