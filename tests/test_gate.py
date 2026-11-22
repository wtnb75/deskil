import json
import re

import pytest

DEF = """\
schema = 1
start = "a"

[states.a]
prompt = "Merge it"
gate = true

[[states.a.choices]]
label = "go"
when = "approved"
goto = "b"

[states.b]
prompt = "Next"
gate = true
goto = "c"

[states.c]
prompt = "Plain"
goto = "e"

[states.e]
prompt = "Done"
end = true
"""


@pytest.fixture
def env(flow, write_def, tmp_path):
    return write_def(tmp_path, DEF), tmp_path / "runs"


def start(flow, env):
    out = flow.start_run(env[0], env[1], cmd="flow")
    return re.search(r"\(run: ([^)]+)\)", out).group(1), out


def nxt(flow, env, rid, label=None, **kw):
    return flow.next_step(rid, label, env[1], cmd="flow", **kw)


def saved(env, rid):
    return json.loads((env[1] / f"{rid}.json").read_text(encoding="utf-8"))


def test_gate_step_shows_guidance_and_approval_hint(flow, env):
    rid, out = start(flow, env)
    assert "Gate: this step needs the user's approval" in out
    assert "AskUserQuestion" in out
    assert f'flow next {rid} --result go --approval "<the user\'s answer>"' in out


def test_gate_step_without_choices_shows_approval_hint(flow, env):
    rid, _ = start(flow, env)
    out = nxt(flow, env, rid, "go", approval="ok")
    assert f'flow next {rid} --approval "<the user\'s answer>"' in out


def test_non_gate_step_has_no_gate_text(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "go", approval="ok")
    out = nxt(flow, env, rid, approval="yes")
    assert out.startswith("[c]")
    assert "Gate:" not in out and "--approval" not in out


@pytest.mark.parametrize("approval", [None, "", "   "])
def test_gate_needs_approval_and_leaves_state_unchanged(flow, env, approval):
    rid, _ = start(flow, env)
    before = (env[1] / f"{rid}.json").read_bytes()
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "go", approval=approval)
    assert "--approval" in str(exc.value)
    assert (env[1] / f"{rid}.json").read_bytes() == before


def test_approval_is_recorded_with_time(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "go", approval="  yes, merge  ")
    entry = saved(env, rid)["history"][0]
    assert entry["approval"] == "yes, merge" and entry["at"]


def test_approval_on_a_non_gate_step_is_error(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "go", approval="ok")
    nxt(flow, env, rid, approval="ok")
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, approval="ok")
    assert "takes no --approval" in str(exc.value)


def test_non_gate_history_has_no_approval_key(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "go", approval="ok")
    nxt(flow, env, rid, approval="ok")
    nxt(flow, env, rid)
    assert "approval" not in saved(env, rid)["history"][2]


def test_status_shows_approval(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "go", approval="yes")
    assert "1. a (result: go) (approval: yes)" in flow.status_text(rid, env[1])


def test_cli_next_takes_approval(flow, env, capsys):
    rid, _ = start(flow, env)
    args = ["next", rid, "--state-dir", str(env[1]), "--result", "go"]
    assert flow.main(args) == 1
    assert "--approval" in capsys.readouterr().err
    assert flow.main([*args, "--approval", "yes"]) == 0


@pytest.mark.parametrize(
    "extra, code",
    [
        ("gate = 1\n", "type"),
        ('gate = "yes"\n', "type"),
    ],
)
def test_lint_rejects_non_boolean_gate(flow, write_def, tmp_path, extra, code):
    text = DEF.replace("gate = true\n", extra, 1)
    issues = flow.lint(write_def(tmp_path, text))
    assert [(i.code, i.where) for i in issues] == [(code, "states.a.gate")]


def test_lint_rejects_gate_on_end_state(flow, write_def, tmp_path):
    text = DEF.replace('prompt = "Done"\n', 'prompt = "Done"\ngate = true\n')
    issues = flow.lint(write_def(tmp_path, text))
    assert [i.code for i in issues] == ["end-with-transition"]


def test_lint_rejects_gate_with_delegate(flow, write_def, tmp_path):
    text = DEF.replace("gate = true\n", 'gate = true\ndelegate = "x"\n', 1)
    issues = flow.lint(write_def(tmp_path, text))
    assert [i.code for i in issues] == ["gate-with-delegate"]


def test_wrong_label_is_reported_before_missing_approval(flow, env):
    rid, _ = start(flow, env)
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "maybe")
    assert "unknown result" in str(exc.value)


def test_dry_run_shows_gate(flow, write_def, tmp_path):
    out = flow.dry_run(write_def(tmp_path, DEF), ["go"])
    assert out.count("Gate: this step needs") == 2


def test_export_keeps_gate_in_text_and_reports_it(flow, write_def, tmp_path):
    md, dropped = flow.export_skill(write_def(tmp_path, DEF), "en")
    assert "Ask the user to confirm before going on" in md
    assert "Not enforced without the flow engine: gate." in md
    assert any("gate" in d for d in dropped)
