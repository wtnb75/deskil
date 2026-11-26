import re
import subprocess
import sys

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

SINGLE_CHOICE = """\
schema = 1
start = "a"

[states.a]
prompt = "A"

[[states.a.choices]]
label = "x"
when = "w"
goto = "b"

[states.b]
prompt = "B"
end = true
"""


@pytest.fixture(autouse=True)
def fixed_cmd(monkeypatch):
    monkeypatch.setenv("FLOW_CMD", "flow")
    monkeypatch.delenv("FLOW_STATE_DIR", raising=False)


@pytest.fixture
def env(write_def, tmp_path):
    return write_def(tmp_path, DEF), tmp_path / "runs"


def start(flow, env, capsys):
    path, sd = env
    assert flow.main(["start", str(path), "--state-dir", str(sd)]) == 0
    out = capsys.readouterr().out
    return re.search(r"\(run: ([^)]+)\)", out).group(1), out


def test_start_prints_step_and_exit_0(flow, env, capsys):
    rid, out = start(flow, env, capsys)
    assert out.startswith(f"[a] (run: {rid})\nDo A\n")


def test_next_and_status_roundtrip(flow, env, capsys):
    rid, _ = start(flow, env, capsys)
    sd = str(env[1])
    assert flow.main(["next", rid, "--result", "again", "--state-dir", sd]) == 0
    assert capsys.readouterr().out.startswith("[w]")
    assert flow.main(["status", rid, "--state-dir", sd]) == 0
    assert "Current: w" in capsys.readouterr().out


def test_lint_exit_1_on_error_and_0_on_warning_only(flow, write_def, tmp_path, capsys):
    bad = write_def(
        tmp_path, DEF.replace("[states.e]", "[states.e]\nbogus = 1"), "bad.toml"
    )
    assert flow.main(["lint", str(bad)]) == 1
    assert "error[unknown-key]" in capsys.readouterr().out

    warn = write_def(tmp_path, SINGLE_CHOICE, "warn.toml")
    assert flow.main(["lint", str(warn)]) == 0
    assert "warning[single-choice]" in capsys.readouterr().out


def test_lint_clean_definition_exit_0(flow, env, capsys):
    assert flow.main(["lint", str(env[0])]) == 0


def test_error_goes_to_stderr_with_prefix(flow, env, capsys):
    assert flow.main(["next", "nope", "--result", "x", "--state-dir", str(env[1])]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: run not found: nope")
    assert captured.out == ""


def test_run_not_found_mentions_state_dir(flow, env, tmp_path, capsys):
    rid, _ = start(flow, env, capsys)
    other = tmp_path / "elsewhere"
    assert flow.main(["next", rid, "--result", "stop", "--state-dir", str(other)]) == 1
    assert str(other) in capsys.readouterr().err


def test_cmd_prefix_from_env(flow, env, capsys, monkeypatch):
    monkeypatch.setenv("FLOW_CMD", "myflow")
    _, out = start(flow, env, capsys)
    assert "  myflow next " in out


def test_default_cmd_prefix_uses_script_path(flow, env, capsys, monkeypatch):
    monkeypatch.delenv("FLOW_CMD")
    monkeypatch.setattr(sys, "argv", ["/opt/p/flow.py"])
    _, out = start(flow, env, capsys)
    assert "  uv run /opt/p/flow.py next " in out


def test_default_state_dir_is_cwd_dot_flow(flow, env, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert flow.main(["start", str(env[0])]) == 0
    assert list((tmp_path / ".flow" / "runs").glob("*.json"))


def test_state_dir_from_env(flow, env, tmp_path, monkeypatch, capsys):
    target = tmp_path / "custom"
    monkeypatch.setenv("FLOW_STATE_DIR", str(target))
    assert flow.main(["start", str(env[0])]) == 0
    assert list(target.glob("*.json"))


def test_state_dir_from_env_expands_tilde(flow, env, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("FLOW_STATE_DIR", "~/flow")
    monkeypatch.chdir(tmp_path)
    assert flow.main(["start", str(env[0])]) == 0
    assert list((tmp_path / "flow").glob("*.json"))
    assert not (tmp_path / "~").exists()


def test_usage_error_exits_2(flow):
    with pytest.raises(SystemExit) as exc:
        flow.main([])
    assert exc.value.code == 2


def test_subprocess_smoke(flow, env, write_def, tmp_path):
    ok = subprocess.run(
        [sys.executable, flow.__file__, "lint", str(env[0])],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0

    bad = write_def(
        tmp_path, DEF.replace("[states.e]", "[states.e]\nbogus = 1"), "bad.toml"
    )
    res = subprocess.run(
        [sys.executable, flow.__file__, "lint", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "error[unknown-key]" in res.stdout


def test_default_cmd_prefix_quotes_a_path_with_spaces(flow, env, capsys, monkeypatch):
    monkeypatch.delenv("FLOW_CMD")
    monkeypatch.setattr(sys, "argv", ["/opt/my p/flow.py"])
    _, out = start(flow, env, capsys)
    assert "  uv run '/opt/my p/flow.py' next " in out


def test_default_state_dir_is_the_git_root(flow, env, tmp_path, monkeypatch):
    import subprocess

    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.chdir(repo / "sub")
    assert flow.main(["start", str(env[0])]) == 0
    assert list((repo / ".flow" / "runs").glob("*.json"))
    assert not (repo / "sub" / ".flow").exists()
