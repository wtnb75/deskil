import json
import re

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
on_exceed = "x"

[states.e]
prompt = "Done"
end = true

[states.x]
prompt = "Gave up"
end = true
"""

ALT = 'schema = 1\nstart = "z"\n[states.z]\nprompt = "Z"\nend = true\n'


@pytest.fixture
def env(flow, write_def, tmp_path):
    """(definition path, state dir)"""
    return write_def(tmp_path, DEF), tmp_path / "runs"


def start(flow, env):
    path, state_dir = env
    out = flow.start_run(path, state_dir, cmd="flow")
    return re.search(r"\(run: ([^)]+)\)", out).group(1), out


def nxt(flow, env, rid, label=None, **kw):
    return flow.next_step(rid, label, env[1], cmd="flow", **kw)


def saved(env, rid):
    return json.loads((env[1] / f"{rid}.json").read_text(encoding="utf-8"))


def test_start_returns_first_step_and_saves_run(flow, env):
    rid, out = start(flow, env)
    assert out.startswith(f"[a] (run: {rid})\nDo A\n")
    data = saved(env, rid)
    assert data["current"] == "a" and data["visits"] == {"a": 1}
    assert data["status"] == "running"


def test_state_file_is_valid_json_with_schema_1(flow, env):
    rid, _ = start(flow, env)
    data = saved(env, rid)
    assert data["schema"] == 1
    assert set(data) >= {
        "run_id",
        "definition",
        "definition_hash",
        "current",
        "visits",
        "history",
        "status",
    }
    assert re.fullmatch(r"\d{8}-\d{4}-[a-z0-9]{3}", rid)


def test_next_follows_label_and_records_history(flow, env):
    rid, _ = start(flow, env)
    out = nxt(flow, env, rid, "again")
    assert out.startswith("[w]")
    data = saved(env, rid)
    assert data["current"] == "w" and data["visits"] == {"a": 1, "w": 1}
    assert [(h["state"], h["label"]) for h in data["history"]] == [("a", "again")]
    assert data["history"][0]["at"]


def test_goto_step_needs_no_result(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "again")
    assert nxt(flow, env, rid).startswith("[a]")


def test_max_visits(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "again")  # w (1st)
    nxt(flow, env, rid)  # a
    nxt(flow, env, rid, "again")  # w (2nd)
    nxt(flow, env, rid)  # a
    out = nxt(flow, env, rid, "again")  # w would be a 3rd entry -> on_exceed
    assert out.startswith("[x]") and out.endswith("Flow complete.\n")
    data = saved(env, rid)
    assert data["status"] == "ended" and data["visits"]["w"] == 2


def test_step_target_applies_max_visits(flow, env):
    defn = flow.load_definition(env[0])
    assert flow.step_target(defn, {"w": 1}, "a", "again") == "w"
    assert flow.step_target(defn, {"w": 2}, "a", "again") == "x"


def test_label_given_to_goto_step_is_error(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "again")
    before = (env[1] / f"{rid}.json").read_bytes()
    with pytest.raises(flow.FlowError):
        nxt(flow, env, rid, "again")
    assert (env[1] / f"{rid}.json").read_bytes() == before


def test_missing_label_on_choice_step_is_error(flow, env):
    rid, _ = start(flow, env)
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid)
    assert "again" in str(exc.value) and "stop" in str(exc.value)


def test_unknown_label_leaves_state_unchanged_and_lists_choices(flow, env):
    rid, _ = start(flow, env)
    before = (env[1] / f"{rid}.json").read_bytes()
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "AGAIN")
    assert "again" in str(exc.value) and "stop" in str(exc.value)
    assert (env[1] / f"{rid}.json").read_bytes() == before


def test_next_on_ended_run_is_error(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "stop")
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "stop")
    assert "ended" in str(exc.value)


def test_unknown_run_id_is_error(flow, env):
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, "nope")
    assert f"run not found: nope (looked in {env[1]})" in str(exc.value)


def test_corrupt_state_file_is_error(flow, env):
    rid, _ = start(flow, env)
    (env[1] / f"{rid}.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "stop")
    assert "corrupt" in str(exc.value)


def test_definition_deleted_after_start_is_error(flow, env):
    rid, _ = start(flow, env)
    env[0].unlink()
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "stop")
    assert "definition not found" in str(exc.value)


def test_definition_changed_is_refused_without_force(flow, env):
    rid, _ = start(flow, env)
    env[0].write_text(DEF + "\n# edited\n", encoding="utf-8")
    before = (env[1] / f"{rid}.json").read_bytes()
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "stop")
    assert "--force" in str(exc.value)
    assert (env[1] / f"{rid}.json").read_bytes() == before


def test_force_continues_with_new_hash(flow, env):
    rid, _ = start(flow, env)
    env[0].write_text(DEF + "\n# edited\n", encoding="utf-8")
    assert nxt(flow, env, rid, "again", force=True).startswith("[w]")
    # The new hash was stored, so the next call needs no --force.
    assert nxt(flow, env, rid).startswith("[a]")


def test_force_with_missing_current_state_is_error(flow, env):
    rid, _ = start(flow, env)
    env[0].write_text(ALT, encoding="utf-8")
    with pytest.raises(flow.FlowError) as exc:
        nxt(flow, env, rid, "stop", force=True)
    assert "no longer exists" in str(exc.value)


def test_status_text_shows_current_visits_history(flow, env):
    rid, _ = start(flow, env)
    nxt(flow, env, rid, "again")
    text = flow.status_text(rid, env[1])
    assert f"Run: {rid}" in text
    assert "Status: running" in text and "Current: w" in text
    assert "a=1" in text and "w=1" in text
    assert "1. a (result: again)" in text


def test_unreadable_definition_is_a_flow_error(flow, env):
    rid, _ = start(flow, env)
    env[0].chmod(0)
    try:
        with pytest.raises(flow.FlowError) as exc:
            nxt(flow, env, rid, "stop")
    finally:
        env[0].chmod(0o644)
    assert "cannot read" in str(exc.value)


def test_new_run_id_reserves_the_run_file(flow, tmp_path, monkeypatch):
    first = flow._new_run_id(tmp_path)
    assert (tmp_path / f"{first}.json").exists()
    picks = iter([list(first[-3:]), list("zzz")])
    monkeypatch.setattr(flow.random, "choices", lambda *a, **k: next(picks))
    second = flow._new_run_id(tmp_path)
    assert second != first
    assert (tmp_path / f"{second}.json").exists()


def test_failed_start_leaves_no_run_file(flow, env, monkeypatch):
    def boom(*a, **k):
        raise flow.FlowError("render failed")

    monkeypatch.setattr(flow, "render_step", boom)
    with pytest.raises(flow.FlowError):
        flow.start_run(env[0], env[1], cmd="flow")
    assert list(env[1].iterdir()) == []


def test_save_run_does_not_depend_on_a_fixed_temp_name(flow, env):
    rid, _ = start(flow, env)
    (env[1] / f"{rid}.json.tmp").mkdir()
    nxt(flow, env, rid, "again")
    names = [f.name for f in env[1].iterdir() if f.suffix != ".lock"]
    assert sorted(names) == [
        f"{rid}.json",
        f"{rid}.json.tmp",
    ]
