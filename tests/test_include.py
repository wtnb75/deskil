"""Tests for `include`: composing a definition from parts (B-017)."""

import subprocess
from pathlib import Path

import pytest

PARENT = """\
schema = 1
start = "a"

[states.a]
prompt = "parent a"
goto = "test"

[states.test]
include = "parts/test.toml"
exits = { ok = "c", fail = "a" }

[states.c]
prompt = "parent c"
end = true
"""

PART = """\
schema = 1
start = "run"

[states.run]
prompt = "run the tests"
choices = [
  { label = "pass", when = "all green", goto = "ok" },
  { label = "retry", when = "flaky", goto = "run" },
  { label = "red", when = "failing", goto = "fail" },
]
max_visits = 2
on_exceed = "fail"

[states.ok]
prompt = "ok"
end = true

[states.fail]
prompt = "fail"
end = true
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def tree(tmp_path):
    """A parent definition that includes parts/test.toml."""
    _write(tmp_path / "parts" / "test.toml", PART)
    return _write(tmp_path / "flow.toml", PARENT)


def codes(flow, path):
    return sorted(i.code for i in flow.lint(path) if i.level == "error")


# --- expansion -------------------------------------------------------------


def test_expands_into_one_state_machine(flow, tree):
    d = flow.load_definition(tree)
    assert list(d.states) == ["a", "test__run", "c"]
    assert (
        d.states["a"].goto == "test__run"
    )  # entry of the include state is the sub's start


def test_edges_to_sub_end_states_go_through_exits(flow, tree):
    d = flow.load_definition(tree)
    run = d.states["test__run"]
    assert {c.label: c.goto for c in run.choices} == {
        "pass": "c",
        "retry": "test__run",
        "red": "a",
    }
    assert run.on_exceed == "a"  # on_exceed to an end state is routed through exits too
    assert run.max_visits == 2


def test_run_walks_through_the_expanded_states(flow, tree, tmp_path):
    state_dir = tmp_path / "runs"
    out = flow.start_run(tree, state_dir)
    run_id = out.split("run: ")[1].split(")")[0]
    out = flow.next_step(run_id, None, state_dir)
    assert "[test__run]" in out
    out = flow.next_step(run_id, "pass", state_dir)
    assert "Flow complete." in out


def test_max_visits_is_counted_inside_the_sub(flow, tree):
    d = flow.load_definition(tree)
    visits = {"test__run": 2}
    assert flow.step_target(d, visits, "test__run", "retry") == "a"


def test_nested_include_uses_chained_names(flow, tmp_path):
    _write(tmp_path / "parts" / "inner.toml", PART)
    _write(
        tmp_path / "parts" / "outer.toml",
        'schema = 1\nstart = "t"\n[states.t]\ninclude = "inner.toml"\n'
        'exits = { ok = "done", fail = "done" }\n[states.done]\nprompt = "d"\nend = true\n',
    )
    p = _write(
        tmp_path / "flow.toml",
        'schema = 1\nstart = "x"\n[states.x]\ninclude = "parts/outer.toml"\n'
        'exits = { done = "z" }\n[states.z]\nprompt = "z"\nend = true\n',
    )
    d = flow.load_definition(p)
    assert list(d.states) == ["x__t__run", "z"]
    assert d.states["x__t__run"].choices[0].goto == "z"


def test_same_part_twice_is_allowed(flow, tmp_path):
    _write(tmp_path / "parts" / "test.toml", PART)
    p = _write(
        tmp_path / "flow.toml",
        'schema = 1\nstart = "t1"\n'
        '[states.t1]\ninclude = "parts/test.toml"\nexits = { ok = "t2", fail = "e" }\n'
        '[states.t2]\ninclude = "parts/test.toml"\nexits = { ok = "e", fail = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    d = flow.load_definition(p)
    assert {"t1__run", "t2__run"} <= set(d.states)
    assert (
        d.states["t1__run"].choices[0].goto == "t2__run"
    )  # exits to another include state


def test_sub_that_starts_at_an_end_state_is_an_error(flow, tmp_path):
    _write(
        tmp_path / "parts" / "test.toml",
        'schema = 1\nstart = "e"\n[states.e]\nprompt = "e"\nend = true\n',
    )
    p = _write(
        tmp_path / "flow.toml",
        'schema = 1\nstart = "t"\n[states.t]\ninclude = "parts/test.toml"\nexits = { e = "f" }\n'
        '[states.f]\nprompt = "f"\nend = true\n',
    )
    assert "include-start-end" in codes(flow, p)


# --- notes -----------------------------------------------------------------


def test_always_notes_stay_with_their_own_definition(flow, tmp_path):
    _write(
        tmp_path / "parts" / "test.toml",
        PART.replace(
            'start = "run"', 'start = "run"\n[notes]\nalways = ["sub rule"]', 1
        ),
    )
    p = _write(
        tmp_path / "flow.toml",
        PARENT.replace(
            'start = "a"\n', 'start = "a"\n[notes]\nalways = ["parent rule"]\n', 1
        ),
    )
    d = flow.load_definition(p)
    assert d.states["a"].always == ("parent rule",)
    assert d.states["test__run"].always == ("sub rule",)
    out = flow.render_step(d, "test__run", "r")
    assert "sub rule" in out and "parent rule" not in out
    out = flow.render_step(d, "a", "r")
    assert "parent rule" in out and "sub rule" not in out


def test_sub_common_notes_are_namespaced(flow, tmp_path):
    part = PART.replace(
        '[states.run]\nprompt = "run the tests"',
        '[notes.common]\nn1 = "sub common"\n\n[states.run]\nprompt = "run the tests"\nnotes = ["n1"]',
    )
    _write(tmp_path / "parts" / "test.toml", part)
    p = _write(tmp_path / "flow.toml", PARENT)
    d = flow.load_definition(p)
    assert "sub common" in flow.render_step(d, "test__run", "r")


# --- lint ------------------------------------------------------------------


def test_exits_must_cover_every_end_state(flow, tree):
    _write(
        tree, PARENT.replace('exits = { ok = "c", fail = "a" }', 'exits = { ok = "c" }')
    )
    assert "exits-missing" in codes(flow, tree)


def test_exits_must_not_name_unknown_end_states(flow, tree):
    _write(tree, PARENT.replace('fail = "a" }', 'fail = "a", nope = "a" }'))
    assert "exits-unknown" in codes(flow, tree)


def test_exits_target_must_exist(flow, tree):
    _write(tree, PARENT.replace('fail = "a"', 'fail = "nowhere"'))
    assert "missing-target" in codes(flow, tree)


def test_include_state_takes_no_other_keys(flow, tree):
    _write(
        tree,
        PARENT.replace(
            'include = "parts/test.toml"', 'include = "parts/test.toml"\nprompt = "x"'
        ),
    )
    assert "include-with-other-keys" in codes(flow, tree)


def test_include_requires_exits(flow, tree):
    _write(tree, PARENT.replace('exits = { ok = "c", fail = "a" }\n', ""))
    assert "exits-missing" in codes(flow, tree)


def test_exits_without_include_is_an_error(flow, tree):
    _write(tree, PARENT.replace('goto = "test"', 'goto = "test"\nexits = {}'))
    assert "exits-without-include" in codes(flow, tree)


@pytest.mark.parametrize("target", ["../x.toml", "/etc/x.toml", "parts/../../x.toml"])
def test_include_path_must_stay_inside(flow, tree, target):
    _write(tree, PARENT.replace("parts/test.toml", target))
    assert "include-outside" in codes(flow, tree)


def test_include_refuses_dotdot_even_when_it_stays_inside(flow, tree):
    # `parts/../parts/test.toml` normalizes to an existing inside path, but is still refused.
    _write(tree, PARENT.replace("parts/test.toml", "parts/../parts/test.toml"))
    assert "include-outside" in codes(flow, tree)


def _repo_with_include(tmp_path, link_target):
    """A git repo holding a definition whose part `parts/lnk` is a symlink to `link_target`."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    (root / "parts").mkdir()
    (root / "parts" / "lnk").symlink_to(link_target)
    return root, _write(
        root / "flow.toml", PARENT.replace("parts/test.toml", "parts/lnk")
    )


def test_include_through_symlink_inside_the_repo_is_allowed(flow, tmp_path):
    root, p = _repo_with_include(tmp_path, "../shared.toml")
    _write(root / "shared.toml", PART)
    assert "include-outside" not in codes(flow, p)


def test_include_through_symlink_outside_the_repo_is_refused(flow, tmp_path):
    outside = _write(tmp_path / "outside.toml", PART)
    _, p = _repo_with_include(tmp_path, outside)
    assert "include-outside" in codes(flow, p)


def test_include_through_symlinked_directory_outside_the_repo_is_refused(
    flow, tmp_path
):
    _write(tmp_path / "elsewhere" / "test.toml", PART)
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    (root / "parts").symlink_to(tmp_path / "elsewhere")
    p = _write(root / "flow.toml", PARENT)
    assert "include-outside" in codes(flow, p)


def test_include_symlink_is_not_checked_without_a_repo(flow, tmp_path):
    # No git repository: there is nothing to compare with, so the link is only followed.
    outside = _write(tmp_path / "outside.toml", PART)
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "lnk").symlink_to(outside)
    p = _write(tmp_path / "flow.toml", PARENT.replace("parts/test.toml", "parts/lnk"))
    assert "include-outside" not in codes(flow, p)


def test_include_file_must_exist(flow, tree):
    _write(tree, PARENT.replace("parts/test.toml", "parts/none.toml"))
    assert "include-missing" in codes(flow, tree)


def test_include_cycle_is_an_error(flow, tmp_path):
    _write(
        tmp_path / "parts" / "a.toml",
        'schema = 1\nstart = "x"\n[states.x]\ninclude = "b.toml"\nexits = { e = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    _write(
        tmp_path / "parts" / "b.toml",
        'schema = 1\nstart = "y"\n[states.y]\ninclude = "a.toml"\nexits = { e = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    p = _write(
        tmp_path / "flow.toml",
        'schema = 1\nstart = "s"\n[states.s]\ninclude = "parts/a.toml"\nexits = { e = "f" }\n'
        '[states.f]\nprompt = "f"\nend = true\n',
    )
    assert "include-cycle" in codes(flow, p)


def test_self_include_is_a_cycle(flow, tmp_path):
    p = _write(
        tmp_path / "flow.toml",
        'schema = 1\nstart = "s"\n[states.s]\ninclude = "flow.toml"\nexits = { f = "f" }\n'
        '[states.f]\nprompt = "f"\nend = true\n',
    )
    assert "include-cycle" in codes(flow, p)


def test_sub_schema_errors_are_reported_with_the_sub_path(flow, tree, tmp_path):
    _write(
        tmp_path / "parts" / "test.toml",
        PART.replace("[states.ok]", "[states.ok]\nbogus = 1"),
    )
    issues = [i for i in flow.lint(tree) if i.code == "unknown-key"]
    assert issues and "parts/test.toml" in issues[0].where


def test_id_collision_is_an_error(flow, tmp_path):
    _write(tmp_path / "parts" / "test.toml", PART)
    p = _write(
        tmp_path / "flow.toml",
        'schema = 1\nstart = "test"\n[states.test]\ninclude = "parts/test.toml"\n'
        'exits = { ok = "e", fail = "e" }\n[states.test__run]\nprompt = "x"\ngoto = "e"\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    assert "id-collision" in codes(flow, p)


def test_graph_lint_sees_through_the_include(flow, tmp_path):
    _write(
        tmp_path / "parts" / "test.toml",
        'schema = 1\nstart = "run"\n[states.run]\nprompt = "p"\ngoto = "ok"\n'
        '[states.lost]\nprompt = "l"\ngoto = "ok"\n'
        '[states.ok]\nprompt = "ok"\nend = true\n[states.fail]\nprompt = "f"\nend = true\n',
    )
    p = _write(tmp_path / "flow.toml", PARENT)
    orphans = [i.where for i in flow.lint(p) if i.code == "orphan"]
    assert orphans == ["states.test__lost"]


# --- paths relative to the part ---------------------------------------------


def test_file_cwd_and_def_dir_are_relative_to_the_part(flow, tmp_path):
    shared = tmp_path / "elsewhere" / "shared"
    _write(shared / "p.md", "prompt from part\n")
    _write(
        shared / "test.toml",
        'schema = 1\nstart = "run"\n[states.run]\nprompt = { file = "p.md" }\n'
        'run = ["${DEF_DIR}/x.sh", "arg"]\ncwd = "work"\ngoto = "ok"\n'
        '[states.ok]\nprompt = "ok"\nend = true\n',
    )
    root = tmp_path / "proj"
    root.mkdir()
    (root / "parts").symlink_to(
        shared
    )  # a symlinked directory outside the definition dir
    p = _write(
        root / "flow.toml",
        'schema = 1\nstart = "t"\n[states.t]\ninclude = "parts/test.toml"\nexits = { ok = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    assert codes(flow, p) == []
    d = flow.load_definition(p)
    st = d.states["t__run"]
    assert st.cwd == "parts/work"
    assert st.run == ("${DEF_DIR}/parts/x.sh", "arg")
    assert "prompt from part" in flow.render_step(d, "t__run", "r")


def test_symlinked_include_file_is_allowed(flow, tmp_path):
    _write(tmp_path / "shared" / "test.toml", PART)
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "parts" / "test.toml").symlink_to(tmp_path / "shared" / "test.toml")
    p = _write(root / "flow.toml", PARENT)
    assert codes(flow, p) == []
    assert "test__run" in flow.load_definition(p).states


def test_sub_file_reference_outside_is_an_error(flow, tmp_path):
    _write(
        tmp_path / "parts" / "test.toml",
        'schema = 1\nstart = "run"\n[states.run]\nprompt = { file = "../x.md" }\ngoto = "ok"\n'
        '[states.ok]\nprompt = "ok"\nend = true\n[states.fail]\nprompt = "f"\nend = true\n',
    )
    _write(tmp_path / "x.md", "x")
    p = _write(tmp_path / "flow.toml", PARENT)
    assert "file-outside" in codes(flow, p)


# --- definition hash ---------------------------------------------------------


def test_hash_is_the_file_hash_without_includes(flow, write_def, tmp_path):
    import hashlib

    p = write_def(
        tmp_path, 'schema = 1\nstart = "a"\n[states.a]\nprompt = "x"\nend = true\n'
    )
    assert flow.load_definition(p).hash == hashlib.sha256(p.read_bytes()).hexdigest()


def test_editing_a_part_changes_the_run_hash(flow, tree, tmp_path):
    state_dir = tmp_path / "runs"
    out = flow.start_run(tree, state_dir)
    run_id = out.split("run: ")[1].split(")")[0]
    (tmp_path / "parts" / "test.toml").write_text(
        PART + "\n# edited\n", encoding="utf-8"
    )
    with pytest.raises(flow.FlowError, match="changed since"):
        flow.next_step(run_id, None, state_dir)
    flow.next_step(run_id, None, state_dir, force=True)


# --- commands in a part run only if every file matches the ref ---------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "parts" / "test.toml",
        'schema = 1\nstart = "run"\n[states.run]\nprompt = "p"\nrun = ["echo", "from-part"]\ngoto = "ok"\n'
        '[states.ok]\nprompt = "ok"\nend = true\n',
    )
    _write(
        root / "flow.toml",
        'schema = 1\nstart = "a"\n[states.a]\nprompt = "first"\ngoto = "t"\n'
        '[states.t]\ninclude = "parts/test.toml"\nexits = { ok = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "def")
    return root


def _first_two_steps(flow, repo, tmp_path, force=False):
    """Start the run (state `a`, no command) and advance into the part's command step."""
    state_dir = tmp_path / "runs"
    out = flow.start_run(repo / "flow.toml", state_dir)
    run_id = out.split("run: ")[1].split(")")[0]
    return run_id, state_dir


def test_part_command_runs_when_all_files_match_ref(flow, repo, tmp_path):
    run_id, state_dir = _first_two_steps(flow, repo, tmp_path)
    out = flow.next_step(run_id, None, state_dir)
    assert "Exit code: 0" in out and "from-part" in out


def test_edited_part_command_is_display_only(flow, repo, tmp_path):
    part = repo / "parts" / "test.toml"
    part.write_text(
        part.read_text(encoding="utf-8").replace("from-part", "evil"), encoding="utf-8"
    )
    run_id, state_dir = _first_two_steps(flow, repo, tmp_path)
    out = flow.next_step(run_id, None, state_dir)
    assert "Command not executed" in out and "evil" in out


def test_force_after_part_edit_does_not_execute(flow, repo, tmp_path):
    run_id, state_dir = _first_two_steps(flow, repo, tmp_path)
    part = repo / "parts" / "test.toml"
    part.write_text(
        part.read_text(encoding="utf-8").replace("from-part", "evil"), encoding="utf-8"
    )
    out = flow.next_step(run_id, None, state_dir, force=True)
    assert "Command not executed" in out and "Exit code" not in out


def test_symlinked_part_is_checked_at_its_real_path(flow, tmp_path):
    root = tmp_path / "repo"
    _write(
        root / "shared" / "test.toml",
        'schema = 1\nstart = "run"\n[states.run]\nprompt = "p"\nrun = ["echo", "linked"]\ngoto = "ok"\n'
        '[states.ok]\nprompt = "ok"\nend = true\n',
    )
    (root / "parts").mkdir()
    (root / "parts" / "test.toml").symlink_to(root / "shared" / "test.toml")
    _write(
        root / "flow.toml",
        'schema = 1\nstart = "t"\n[states.t]\ninclude = "parts/test.toml"\nexits = { ok = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "def")
    out = flow.start_run(root / "flow.toml", tmp_path / "runs")
    assert "Exit code: 0" in out
    shared = root / "shared" / "test.toml"
    shared.write_text(
        shared.read_text(encoding="utf-8").replace("linked", "evil"), encoding="utf-8"
    )
    out = flow.start_run(root / "flow.toml", tmp_path / "runs")
    assert "Command not executed" in out


def test_repointed_symlink_is_display_only(flow, tmp_path):
    """A part symlink re-pointed at another committed file must not pass the ref check."""
    root = tmp_path / "repo"
    for name, word in (("one", "linked"), ("two", "other")):
        _write(
            root / "shared" / f"{name}.toml",
            f'schema = 1\nstart = "run"\n[states.run]\nprompt = "p"\nrun = ["echo", "{word}"]\n'
            'goto = "ok"\n[states.ok]\nprompt = "ok"\nend = true\n',
        )
    (root / "parts").mkdir()
    (root / "parts" / "test.toml").symlink_to(root / "shared" / "one.toml")
    _write(
        root / "flow.toml",
        'schema = 1\nstart = "t"\n[states.t]\ninclude = "parts/test.toml"\nexits = { ok = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "def")
    link = root / "parts" / "test.toml"
    link.unlink()
    link.symlink_to(
        root / "shared" / "two.toml"
    )  # committed content, but not the committed link
    out = flow.start_run(root / "flow.toml", tmp_path / "runs")
    assert "Command not executed" in out and "Exit code" not in out


def _commit_all(root: Path) -> None:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "def")


def test_repointed_link_inside_a_link_target_is_display_only(flow, tmp_path):
    """A symlink met while following another link must also be the committed one."""
    root = tmp_path / "repo"
    for name, word in (("one", "linked"), ("two", "other")):
        _write(
            root / name / "test.toml",
            f'schema = 1\nstart = "run"\n[states.run]\nprompt = "p"\nrun = ["echo", "{word}"]\n'
            'goto = "ok"\n[states.ok]\nprompt = "ok"\nend = true\n',
        )
    (root / "lib").symlink_to("one")
    (root / "parts").mkdir()
    (root / "parts" / "test.toml").symlink_to("../lib/test.toml")
    _write(
        root / "flow.toml",
        'schema = 1\nstart = "t"\n[states.t]\ninclude = "parts/test.toml"\nexits = { ok = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    _commit_all(root)
    out = flow.start_run(root / "flow.toml", tmp_path / "runs")
    assert "Exit code: 0" in out
    (root / "lib").unlink()
    (root / "lib").symlink_to("two")  # committed content, but not the committed link
    out = flow.start_run(root / "flow.toml", tmp_path / "runs")
    assert "Command not executed" in out and "Exit code" not in out


def test_file_path_with_dotdot_is_refused(flow, tmp_path):
    """`a/../b` means different files lexically and through the link `a`, so lint refuses it."""
    root = tmp_path / "proj"
    _write(root / "parts" / "sub" / "dir" / ".keep", "")
    (root / "parts" / "a").symlink_to("sub/dir")
    _write(root / "parts" / "sub" / "b.md", "linted text")
    _write(root / "parts" / "b.md", "other text")
    _write(
        root / "parts" / "test.toml",
        'schema = 1\nstart = "run"\n[states.run]\nprompt = { file = "a/../b.md" }\ngoto = "ok"\n'
        '[states.ok]\nprompt = "ok"\nend = true\n',
    )
    p = _write(
        root / "flow.toml",
        'schema = 1\nstart = "t"\n[states.t]\ninclude = "parts/test.toml"\nexits = { ok = "e" }\n'
        '[states.e]\nprompt = "e"\nend = true\n',
    )
    assert "file-outside" in codes(flow, p)
