"""Per-run locking of `next`, and `gc --corrupt` for leftover run files."""

import re
import sys

import pytest

DEF = 'schema = 1\nstart = "a"\n[states.a]\nprompt = "A"\ngoto = "e"\n[states.e]\nprompt = "E"\nend = true\n'

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="needs fcntl")


@pytest.fixture
def env(flow, write_def, tmp_path):
    return write_def(tmp_path, DEF), tmp_path / "runs"


def new_run(flow, env):
    path, state_dir = env
    out = flow.start_run(path, state_dir, cmd="flow")
    return re.search(r"\(run: ([^)]+)\)", out).group(1)


@posix_only
def test_next_fails_fast_while_the_run_is_locked(flow, env):
    rid = new_run(flow, env)
    with flow._run_lock(env[1], rid), pytest.raises(flow.FlowError) as exc:
        flow.next_step(rid, None, env[1], cmd="flow")
    assert "in use" in str(exc.value)
    # Nothing was written, and the run is usable once the lock is released.
    assert "Flow complete" in flow.next_step(rid, None, env[1], cmd="flow")


@posix_only
def test_lock_is_released_after_an_error(flow, env):
    rid = new_run(flow, env)
    with pytest.raises(flow.FlowError):
        flow.next_step(rid, "no-such-label", env[1], cmd="flow")
    with flow._run_lock(env[1], rid):
        pass


@posix_only
def test_next_does_not_run_its_command_while_locked(flow, write_def, tmp_path):
    marker = tmp_path / "ran"
    text = (
        'schema = 1\nstart = "a"\n[states.a]\nprompt = "A"\ngoto = "b"\n'
        f'[states.b]\nprompt = "B"\nrun = ["touch", "{marker}"]\ngoto = "e"\n'
        '[states.e]\nprompt = "E"\nend = true\n'
    )
    path = write_def(tmp_path, text)
    state_dir = tmp_path / "runs"
    out = flow.start_run(path, state_dir, cmd="flow")
    rid = re.search(r"\(run: ([^)]+)\)", out).group(1)
    with flow._run_lock(state_dir, rid), pytest.raises(flow.FlowError):
        flow.next_step(rid, None, state_dir, cmd="flow")
    assert not marker.exists()


def test_gc_corrupt_removes_unreadable_runs(flow, env):
    env[1].mkdir()
    (env[1] / "bad.json").write_text("{", encoding="utf-8")
    empty = "20260101-0000-abc"
    (env[1] / f"{empty}.json").write_text("", encoding="utf-8")
    (env[1] / f"{empty}.lock").write_text("", encoding="utf-8")
    ok = new_run(flow, env)
    out = flow.gc_runs(env[1], corrupt=True)
    assert empty in out
    assert not (env[1] / f"{empty}.json").exists()
    assert not (env[1] / f"{empty}.lock").exists()
    assert (env[1] / f"{ok}.json").exists()
    assert not (env[1] / "bad.json").exists()


def test_gc_without_corrupt_keeps_unreadable_runs(flow, env):
    env[1].mkdir()
    empty = "20260101-0000-abc"
    (env[1] / f"{empty}.json").write_text("", encoding="utf-8")
    flow.gc_runs(env[1], done=True)
    assert (env[1] / f"{empty}.json").exists()


@posix_only
def test_gc_corrupt_skips_a_locked_file(flow, env):
    env[1].mkdir()
    empty = "20260101-0000-abc"
    (env[1] / f"{empty}.json").write_text("", encoding="utf-8")
    with flow._run_lock(env[1], empty):
        flow.gc_runs(env[1], corrupt=True)
    assert (env[1] / f"{empty}.json").exists()


def test_gc_corrupt_counts_as_a_filter_and_works_from_the_cli(flow, env):
    env[1].mkdir()
    empty = "20260101-0000-abc"
    (env[1] / f"{empty}.json").write_text("", encoding="utf-8")
    assert flow.main(["gc", "--corrupt", "--state-dir", str(env[1])]) == 0
    assert not (env[1] / f"{empty}.json").exists()


@posix_only
def test_gc_removes_the_lock_file_of_a_removed_run(flow, env):
    rid = new_run(flow, env)
    flow.next_step(rid, None, env[1], cmd="flow")
    assert (env[1] / f"{rid}.lock").exists()
    flow.gc_runs(env[1], done=True)
    assert sorted(env[1].iterdir()) == []


def test_gc_rechecks_the_run_after_taking_the_lock(flow, env, monkeypatch):
    # The run is unreadable when scanned, but valid by the time gc holds the lock.
    rid = new_run(flow, env)
    good = flow.load_run(env[1], rid)
    monkeypatch.setattr(flow, "_scan_runs", lambda d: [(rid, None, 0.0)])
    assert good.status == "running"
    flow.gc_runs(env[1], corrupt=True)
    assert (env[1] / f"{rid}.json").exists()


@posix_only
def test_start_holds_the_lock_while_the_run_file_is_empty(flow, env):
    import contextlib

    with contextlib.ExitStack() as stack:
        rid = flow._new_run_id(env[1], stack)
        assert (env[1] / f"{rid}.json").stat().st_size == 0
        assert flow.gc_runs(env[1], corrupt=True) == "no runs removed\n"
        assert (env[1] / f"{rid}.json").exists()


def test_next_on_a_missing_run_leaves_no_lock_file(flow, env):
    env[1].mkdir()
    with pytest.raises(flow.FlowError):
        flow.next_step("20260101-0000-abc", None, env[1], cmd="flow")
    assert list(env[1].iterdir()) == []
