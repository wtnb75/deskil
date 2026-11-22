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
goto = "e"

[states.w]
prompt = "Work"
goto = "a"
max_visits = 2
on_exceed = "e"

[states.e]
prompt = "Done"
end = true
"""


@pytest.fixture
def path(write_def, tmp_path):
    return write_def(tmp_path, DEF)


@pytest.fixture
def scen(write_def, tmp_path):
    def _write(text: str):
        return write_def(tmp_path, text, "scenario.toml")

    return _write


def test_passing_scenarios(flow, path, scen):
    sc = scen(
        """\
[[scenario]]
name = "stop at once"
choices = ["stop"]
expect = ["a", "e"]

[[scenario]]
name = "one loop"
choices = ["again", "stop"]
expect = ["a", "w", "a", "e"]
"""
    )
    out, ok = flow.run_scenarios(path, sc)
    assert ok
    assert "ok: stop at once" in out
    assert "ok: one loop" in out


def test_on_exceed_path(flow, path, scen):
    sc = scen(
        """\
[[scenario]]
name = "limit"
choices = ["again", "again", "again"]
expect = ["a", "w", "a", "w", "a", "e"]
"""
    )
    out, ok = flow.run_scenarios(path, sc)
    assert ok, out


def test_wrong_expectation_fails(flow, path, scen):
    sc = scen(
        """\
[[scenario]]
name = "bad"
choices = ["stop"]
expect = ["a", "w", "e"]
"""
    )
    out, ok = flow.run_scenarios(path, sc)
    assert not ok
    assert "FAIL: bad" in out
    assert "a -> e" in out


def test_unknown_choice_fails(flow, path, scen):
    sc = scen(
        """\
[[scenario]]
name = "typo"
choices = ["nope"]
expect = ["a", "e"]
"""
    )
    out, ok = flow.run_scenarios(path, sc)
    assert not ok
    assert "unknown result 'nope'" in out


def test_choices_exhausted_and_left_over(flow, path, scen):
    sc = scen(
        """\
[[scenario]]
name = "short"
choices = []
expect = ["a"]

[[scenario]]
name = "long"
choices = ["stop", "stop"]
expect = ["a", "e"]
"""
    )
    out, ok = flow.run_scenarios(path, sc)
    assert not ok
    assert "FAIL: short" in out and "exhausted" in out
    assert "FAIL: long" in out and "left over" in out


@pytest.mark.parametrize(
    "text",
    [
        "x = 1\n",
        "scenario = [1]\n",
        '[[scenario]]\nname = "n"\nchoices = []\n',
        '[[scenario]]\nname = "n"\nchoices = "stop"\nexpect = []\n',
        '[[scenario]]\nname = "n"\nchoices = []\nexpect = []\nextra = 1\n',
    ],
)
def test_invalid_scenario_file(flow, path, scen, text):
    with pytest.raises(flow.FlowError):
        flow.run_scenarios(path, scen(text))


def test_cli(flow, path, scen, capsys):
    sc = scen('[[scenario]]\nname = "s"\nchoices = ["stop"]\nexpect = ["a", "e"]\n')
    assert flow.main(["test", str(path), str(sc)]) == 0
    assert "ok: s" in capsys.readouterr().out
    bad = scen('[[scenario]]\nname = "s"\nchoices = ["stop"]\nexpect = ["a"]\n')
    assert flow.main(["test", str(path), str(bad)]) == 1
