"""`flow runs` (list) and `flow gc` (delete old / ended runs)."""

import os
import re
import time

import pytest

DEF = 'schema = 1\nstart = "a"\n[states.a]\nprompt = "A"\ngoto = "e"\n[states.e]\nprompt = "E"\nend = true\n'


@pytest.fixture
def env(flow, write_def, tmp_path):
    return write_def(tmp_path, DEF), tmp_path / "runs"


def new_run(flow, env, finish=False):
    path, state_dir = env
    out = flow.start_run(path, state_dir, cmd="flow")
    rid = re.search(r"\(run: ([^)]+)\)", out).group(1)
    if finish:
        flow.next_step(rid, None, state_dir, cmd="flow")
    return rid


def age(state_dir, rid, days):
    t = time.time() - days * 86400
    os.utime(state_dir / f"{rid}.json", (t, t))


def test_runs_empty(flow, tmp_path):
    assert "no runs" in flow.runs_text(tmp_path / "none")


def test_runs_lists_status_definition_and_time(flow, env):
    a = new_run(flow, env)
    b = new_run(flow, env, finish=True)
    out = flow.runs_text(env[1])
    assert a in out and b in out
    assert "running" in out and "ended" in out
    assert str(env[0]) in out
    assert re.search(r"\d{4}-\d\d-\d\d \d\d:\d\d", out)


def test_runs_marks_corrupt_file(flow, env):
    env[1].mkdir()
    (env[1] / "bad.json").write_text("{", encoding="utf-8")
    assert "corrupt" in flow.runs_text(env[1])


def test_gc_requires_a_filter(flow, env):
    with pytest.raises(flow.FlowError):
        flow.gc_runs(env[1])


@pytest.mark.parametrize("bad", [float("nan"), -1, float("inf")])
def test_gc_rejects_bad_days(flow, env, bad):
    rid = new_run(flow, env)
    with pytest.raises(flow.FlowError):
        flow.gc_runs(env[1], older_than=bad)
    assert (env[1] / f"{rid}.json").exists()


def test_gc_done_removes_only_ended(flow, env):
    run = new_run(flow, env)
    done = new_run(flow, env, finish=True)
    (env[1] / done).mkdir()
    (env[1] / done / "x.out").write_text("o", encoding="utf-8")
    out = flow.gc_runs(env[1], done=True)
    assert done in out
    assert not (env[1] / f"{done}.json").exists()
    assert not (env[1] / done).exists()
    assert (env[1] / f"{run}.json").exists()


def test_gc_older_than(flow, env):
    old = new_run(flow, env)
    new = new_run(flow, env)
    age(env[1], old, 10)
    flow.gc_runs(env[1], older_than=7)
    assert not (env[1] / f"{old}.json").exists()
    assert (env[1] / f"{new}.json").exists()


def test_gc_both_filters_must_match(flow, env):
    old_running = new_run(flow, env)
    old_done = new_run(flow, env, finish=True)
    new_done = new_run(flow, env, finish=True)
    for rid in (old_running, old_done):
        age(env[1], rid, 10)
    flow.gc_runs(env[1], older_than=7, done=True)
    assert (env[1] / f"{old_running}.json").exists()
    assert not (env[1] / f"{old_done}.json").exists()
    assert (env[1] / f"{new_done}.json").exists()


def test_gc_keeps_corrupt_files(flow, env):
    env[1].mkdir()
    (env[1] / "bad.json").write_text("{", encoding="utf-8")
    flow.gc_runs(env[1], done=True)
    assert (env[1] / "bad.json").exists()


def test_cli(flow, env, capsys):
    rid = new_run(flow, env, finish=True)
    assert flow.main(["runs", "--state-dir", str(env[1])]) == 0
    assert rid in capsys.readouterr().out
    assert flow.main(["gc", "--state-dir", str(env[1])]) == 1
    assert flow.main(["gc", "--done", "--state-dir", str(env[1])]) == 0
    assert not (env[1] / f"{rid}.json").exists()
