"""Tests for running commands written in a definition (B-013)."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _def(run: str, extra: str = "") -> str:
    return f"""\
schema = 1
start = "a"

[states.a]
prompt = "Run it"
run = {run}
{extra}
goto = "e"

[states.e]
prompt = "Done"
end = true
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A git repo whose branch main holds the definition (committed by `commit`)."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def commit(repo: Path, text: str) -> Path:
    path = repo / "flow.toml"
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "flow.toml")
    _git(repo, "commit", "-m", "def")
    return path


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "runs"


def py(code: str) -> str:
    return json.dumps([sys.executable, "-c", code])


# --- lint -------------------------------------------------------------------


def codes(flow, tmp_path, write_def, text):
    return {i.code for i in flow.lint(write_def(tmp_path, text)) if i.level == "error"}


def test_lint_accepts_run_options(flow, tmp_path, write_def):
    text = _def('["echo", "hi"]', 'timeout = 5\ncwd = "sub"\noutput_lines = 10')
    assert codes(flow, tmp_path, write_def, text) == set()


@pytest.mark.parametrize("value", ['"echo hi"', "[]", '["echo", 1]', "[1]", '[""]'])
def test_lint_rejects_bad_run(flow, tmp_path, write_def, value):
    assert "type" in codes(flow, tmp_path, write_def, _def(value))


@pytest.mark.parametrize(
    "extra",
    [
        "timeout = 0",
        "timeout = true",
        'timeout = "5"',
        "output_lines = 0",
        "output_lines = true",
        "cwd = 3",
    ],
)
def test_lint_rejects_bad_option_values(flow, tmp_path, write_def, extra):
    assert "type" in codes(flow, tmp_path, write_def, _def('["true"]', extra))


@pytest.mark.parametrize("key", ["timeout = 5", 'cwd = "x"', "output_lines = 5"])
def test_lint_options_need_run(flow, tmp_path, write_def, key):
    text = (
        f'schema = 1\nstart = "a"\n[states.a]\nprompt = "p"\n{key}\ngoto = "e"\n'
        '[states.e]\nprompt = "d"\nend = true\n'
    )
    assert "option-without-run" in codes(flow, tmp_path, write_def, text)


def test_lint_cwd_must_stay_inside_definition_dir(flow, tmp_path, write_def):
    for bad in ('"/abs"', '"../up"'):
        assert "cwd-outside" in codes(
            flow, tmp_path, write_def, _def('["true"]', f"cwd = {bad}")
        )


def test_lint_end_state_cannot_run(flow, tmp_path, write_def):
    text = 'schema = 1\nstart = "e"\n[states.e]\nprompt = "d"\nrun = ["true"]\nend = true\n'
    assert "end-with-transition" in codes(flow, tmp_path, write_def, text)


# --- execution gate ---------------------------------------------------------


def test_runs_command_when_definition_matches_ref(flow, repo, state_dir):
    path = commit(repo, _def(py("print('hello')")))
    out = flow.start_run(path, state_dir)
    assert "Exit code: 0" in out
    assert "hello" in out


def test_definition_modified_in_worktree_is_display_only(flow, repo, state_dir):
    path = commit(repo, _def(py("print('hello')")))
    path.write_text(_def(py("print('changed')")), encoding="utf-8")
    out = flow.start_run(path, state_dir)
    assert "not executed" in out.lower()
    assert "changed" in out  # the command itself is shown
    assert "Exit code" not in out


def test_force_after_edit_does_not_execute(flow, repo, state_dir, tmp_path):
    two = """\
schema = 1
start = "p"

[states.p]
prompt = "plain"
goto = "a"

[states.a]
prompt = "Run it"
run = %s
goto = "e"

[states.e]
prompt = "Done"
end = true
"""
    path = commit(repo, two % py("print('ok')"))
    out = flow.start_run(path, state_dir, "flow")
    run_id = out.split("run: ")[1].split(")")[0]
    path.write_text(two % py("print('evil')"), encoding="utf-8")
    out = flow.next_step(run_id, None, state_dir, "flow", force=True)
    assert "not executed" in out.lower()
    assert "Exit code" not in out


def test_not_a_git_repo_is_display_only(flow, tmp_path, write_def, state_dir):
    path = write_def(tmp_path, _def(py("print('x')")))
    out = flow.start_run(path, state_dir)
    assert "not executed" in out.lower()


def test_missing_ref_is_display_only(flow, repo, state_dir):
    path = commit(repo, _def(py("print('x')")))
    out = flow.start_run(path, state_dir, ref="no-such-ref")
    assert "not executed" in out.lower()
    assert "no-such-ref" in out


def test_file_absent_from_ref_is_display_only(flow, repo, state_dir):
    commit(repo, _def(py("print('x')")))
    other = repo / "other.toml"
    other.write_text(_def(py("print('x')")), encoding="utf-8")
    out = flow.start_run(other, state_dir)
    assert "not executed" in out.lower()


def test_ref_option_selects_branch(flow, repo, state_dir):
    path = commit(repo, _def(py("print('x')")))
    _git(repo, "switch", "-c", "feature")
    out = flow.start_run(path, state_dir, ref="feature")
    assert "Exit code: 0" in out


def test_dry_run_never_executes(flow, repo):
    marker = repo / "marker"
    path = commit(repo, _def(py(f"open({str(marker)!r}, 'w')")))
    out = flow.dry_run(path, None)
    assert not marker.exists()
    assert "not executed" in out.lower()


# --- results ----------------------------------------------------------------


def run_one(flow, repo, state_dir, code, extra=""):
    path = commit(repo, _def(py(code), extra))
    return flow.start_run(path, state_dir)


def test_nonzero_exit_code_is_reported(flow, repo, state_dir):
    out = run_one(flow, repo, state_dir, "import sys; sys.exit(3)")
    assert "Exit code: 3" in out


def test_stdout_and_stderr_are_separate(flow, repo, state_dir):
    out = run_one(
        flow,
        repo,
        state_dir,
        "import sys; print('o'+'ut1'); print('e'+'rr1', file=sys.stderr)",
    )
    assert (
        out.index("stdout (")
        < out.index("\nout1")
        < out.index("stderr (")
        < out.index("\nerr1")
    )


def test_output_is_truncated_from_the_head(flow, repo, state_dir):
    out = run_one(
        flow,
        repo,
        state_dir,
        "print('\\n'.join(f'line{i}' for i in range(1, 251)))",
        "output_lines = 100",
    )
    assert "line250" in out
    assert "line151" in out
    assert "line150\n" not in out
    assert "150 lines truncated" in out


def test_default_limit_is_100_lines(flow, repo, state_dir):
    out = run_one(
        flow, repo, state_dir, "print('\\n'.join(f'line{i}' for i in range(1, 121)))"
    )
    assert "20 lines truncated" in out


def test_full_output_is_saved_in_run_directory(flow, repo, state_dir):
    out = run_one(
        flow,
        repo,
        state_dir,
        "print('\\n'.join(f'line{i}' for i in range(1, 251)))",
        "output_lines = 10",
    )
    saved = list(state_dir.glob("*/*.stdout"))
    assert len(saved) == 1
    assert saved[0].read_text().splitlines()[0] == "line1"
    assert str(saved[0]) in out


def test_result_is_recorded_in_run_file(flow, repo, state_dir):
    run_one(flow, repo, state_dir, "print('hi')")
    data = json.loads(next(state_dir.glob("*.json")).read_text())
    (rec,) = data["commands"]
    assert rec["state"] == "a"
    assert rec["exit_code"] == 0
    assert rec["stdout"].strip() == "hi"
    assert rec["executed"] is True


def test_timeout_kills_process_group_and_reports(flow, repo, state_dir):
    path = commit(
        repo,
        'schema = 1\nstart = "a"\n[states.a]\nprompt = "p"\n'
        'run = ["sh", "-c", "echo before; sleep 30; true"]\ntimeout = 1\n'
        'goto = "e"\n[states.e]\nprompt = "d"\nend = true\n',
    )
    t0 = time.monotonic()
    out = flow.start_run(path, state_dir)
    assert time.monotonic() - t0 < 10
    assert "timeout" in out.lower()
    assert "before" in out


def test_missing_binary_is_reported_not_raised(flow, repo, state_dir):
    path = commit(repo, _def('["definitely-not-a-command-xyz"]'))
    out = flow.start_run(path, state_dir)
    assert "failed to start" in out.lower()


def test_missing_cwd_is_reported_not_raised(flow, repo, state_dir):
    path = commit(repo, _def('["true"]', 'cwd = "nodir"'))
    out = flow.start_run(path, state_dir)
    assert "failed to start" in out.lower()


def test_cwd_is_relative_to_definition_dir(flow, repo, state_dir):
    (repo / "sub").mkdir()
    (repo / "sub" / "f.txt").write_text("x")
    path = commit(
        repo, _def(py("import os; print(sorted(os.listdir('.')))"), 'cwd = "sub"')
    )
    out = flow.start_run(path, state_dir)
    assert "f.txt" in out


def test_default_cwd_is_where_start_ran(flow, repo, state_dir, tmp_path, monkeypatch):
    where = tmp_path / "elsewhere"
    where.mkdir()
    monkeypatch.chdir(where)
    path = commit(repo, _def(py("import os; print(os.getcwd())")))
    out = flow.start_run(path, state_dir)
    assert str(where.resolve()) in out


def test_command_is_not_run_through_a_shell(flow, repo, state_dir):
    path = commit(
        repo,
        _def(
            json.dumps(
                [
                    sys.executable,
                    "-c",
                    "import sys; print(sys.argv[1:])",
                    "a b",
                    "$HOME",
                    ";",
                    "echo",
                ]
            )
        ),
    )
    out = flow.start_run(path, state_dir)
    assert "['a b', '$HOME', ';', 'echo']" in out


def test_loop_does_not_overwrite_saved_output(flow, repo, state_dir):
    text = """\
schema = 1
start = "a"

[states.a]
prompt = "p"
run = RUNARGV
output_lines = 1
goto = "b"

[states.b]
prompt = "again?"
goto = "a"
max_visits = 2
on_exceed = "e"

[states.e]
prompt = "d"
end = true
""".replace("RUNARGV", py("print('x\\n'*5)"))
    path = commit(repo, text)
    out = flow.start_run(path, state_dir)
    run_id = out.split("run: ")[1].split(")")[0]
    flow.next_step(run_id, None, state_dir)
    flow.next_step(run_id, None, state_dir)
    assert len(list(state_dir.glob("*/*.stdout"))) == 2


def test_old_run_file_without_new_fields_still_loads(flow, state_dir):
    state_dir.mkdir()
    (state_dir / "old.json").write_text(
        json.dumps(
            {
                "run_id": "old",
                "definition": "/x",
                "definition_hash": "h",
                "current": "a",
                "visits": {"a": 1},
                "history": [],
                "status": "running",
            }
        )
    )
    run = flow.load_run(state_dir, "old")
    assert run.commands == []


# --- ${DEF_DIR} -------------------------------------------------------------


def argv_def(*extra: str) -> str:
    """A definition whose command prints its own arguments (after -c code)."""
    code = "import sys; print(repr(sys.argv[1:]))"
    return _def(json.dumps([sys.executable, "-c", code, *extra]))


def test_lint_warns_on_unknown_variable(flow, tmp_path, write_def):
    for bad in ("${DEFDIR}/x", "${HOME}"):
        issues = flow.lint(write_def(tmp_path, _def(json.dumps(["echo", bad]))))
        assert [i.code for i in issues if i.level == "warning"] == ["unknown-variable"]
        assert not [i for i in issues if i.level == "error"]


def test_lint_accepts_def_dir(flow, tmp_path, write_def):
    issues = flow.lint(write_def(tmp_path, _def(json.dumps(["echo", "${DEF_DIR}/x"]))))
    assert issues == []


def test_def_dir_is_expanded_before_running(flow, repo, state_dir):
    path = commit(repo, argv_def("${DEF_DIR}/x"))
    out = flow.start_run(path, state_dir)
    assert f"['{repo / 'x'}']" in out  # printed by the child: what it really received
    assert "Exit code: 0" in out


def test_def_dir_with_space_stays_one_argument(flow, tmp_path, state_dir):
    repo = tmp_path / "a b"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    path = commit(repo, argv_def("${DEF_DIR}/x", "y"))
    out = flow.start_run(path, state_dir)
    assert "['" in out and "a b/x', 'y']" in out


def test_multiple_def_dir_in_one_element(flow, repo, state_dir):
    path = commit(repo, argv_def("${DEF_DIR}:${DEF_DIR}"))
    out = flow.start_run(path, state_dir)
    assert f"['{repo}:{repo}']" in out  # printed by the child


def test_other_variables_are_passed_through(flow, repo, state_dir):
    path = commit(repo, argv_def("${HOME}"))
    out = flow.start_run(path, state_dir)
    assert "${HOME}" in out


def test_not_executed_shows_expanded_argv(flow, repo, state_dir):
    path = commit(repo, argv_def("${DEF_DIR}/x"))
    path.write_text(argv_def("${DEF_DIR}/y"), encoding="utf-8")
    out = flow.start_run(path, state_dir)
    assert "not executed" in out.lower()
    assert str(repo / "y") in out
    assert "${DEF_DIR}" not in out


def test_command_edited_in_worktree_is_not_executed_even_with_def_dir(
    flow, repo, state_dir
):
    path = commit(repo, argv_def("${DEF_DIR}/a"))
    path.write_text(argv_def("${DEF_DIR}/b"), encoding="utf-8")
    out = flow.start_run(path, state_dir)
    assert "Exit code" not in out


def test_run_record_holds_expanded_argv(flow, repo, state_dir):
    path = commit(repo, argv_def("${DEF_DIR}/x"))
    flow.start_run(path, state_dir)
    data = json.loads(next(state_dir.glob("*.json")).read_text())
    assert data["commands"][0]["argv"][-1] == str(repo / "x")
