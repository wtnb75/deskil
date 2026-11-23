"""Tests for shared/backlog/backlog.py."""

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = """\
# バックログ

## 運用ルール

```
### B-NNN タイトル
- 状態: todo
```

## todo / ready

### B-001 First
- 状態: ready
- 優先度: P2
- 追加: 2026-11-01
- 背景: bg
- 概要: sum
- 判断: decided

### B-002 Second
- 状態: todo
- 優先度: P1
- 依存: B-001
- 追加: 2026-11-02
- 背景: bg
- 概要: sum

### B-003 Third
- 状態: todo
- 優先度: P3
- 追加: 2026-11-03
- 背景: bg
- 概要: sum

## done / dropped

### B-004 Finished
- 状態: done
- 優先度: P2
- 追加: 2026-10-01
- 背景: bg
- 概要: sum
- 完了: 2026-10-02
- PR: #1
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "BACKLOG.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- parse -----------------------------------------------------------------


def test_parse_ignores_headings_inside_code_fences(backlog):
    bl = backlog.parse(SAMPLE)
    assert [i.id for i in bl.items] == ["B-001", "B-002", "B-003", "B-004"]
    assert bl.problems == []


def test_parse_reads_fields_and_line_ranges(backlog):
    bl = backlog.parse(SAMPLE)
    item = bl.items[1]
    assert item.title == "Second"
    assert item.section == backlog.SECTION_ACTIVE
    assert item.get("優先度") == "P1"
    assert item.get("依存") == "B-001"
    assert item.get("完了") is None
    assert bl.lines[item.start] == "### B-002 Second"
    assert bl.lines[item.end] == "### B-003 Third"
    assert bl.items[3].section == backlog.SECTION_ARCHIVE


def test_parse_reports_malformed_headings(backlog):
    text = SAMPLE.replace("### B-003 Third", "### B-3 Third")
    bl = backlog.parse(text)
    assert [i.id for i in bl.items] == ["B-001", "B-002", "B-004"]
    assert len(bl.problems) == 1
    assert bl.problems[0].line == text.splitlines().index("### B-3 Third") + 1


# --- next-id ---------------------------------------------------------------


def test_next_id(backlog):
    assert backlog.next_id(backlog.parse(SAMPLE)) == "B-005"
    assert backlog.next_id(backlog.parse("# バックログ\n")) == "B-001"
    assert backlog.next_id(backlog.parse(SAMPLE), {7, 2}) == "B-008"
    assert backlog.next_id(backlog.parse(SAMPLE), {2}) == "B-005"


def _git(cwd, *args, date=None):
    env = {**os.environ}
    if date:
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=env,
    )


def _item(n: int) -> str:
    return (
        SAMPLE
        + f"\n### B-{n:03d} Remote\n- 状態: todo\n- 追加: 2026-01-01\n- 背景: b\n- 概要: s\n"
    )


def _origin_and_clone(tmp_path, branches):
    """An origin whose main holds SAMPLE; `branches` maps a branch name to the id it adds
    (None: the branch deletes the backlog). Returns the clone, whose cwd tests should use."""
    remote = tmp_path / "remote"
    work = tmp_path / "work"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    (remote / "docs").mkdir()
    (remote / "docs/BACKLOG.md").write_text(SAMPLE, encoding="utf-8")
    _git(remote, "add", ".")
    _git(remote, "commit", "-q", "-m", "x")
    for day, (name, n) in enumerate(branches.items(), start=1):
        _git(remote, "switch", "-q", "-c", name, "main")
        if n is None:
            _git(remote, "rm", "-q", "docs/BACKLOG.md")
        else:
            (remote / "docs/BACKLOG.md").write_text(_item(n), encoding="utf-8")
        _git(remote, "commit", "-q", "-am", name, date=f"2026-01-{day:02d}T00:00:00")
        _git(remote, "switch", "-q", "main")
    _git(tmp_path, "clone", "-q", str(remote), str(work))
    return work


def test_remote_id_numbers_reads_default_and_pending_branches(
    backlog, tmp_path, monkeypatch
):
    work = _origin_and_clone(
        tmp_path,
        {"backlog/B-011-x": 11, "docs/y": 12, "feature/z": 99, "backlog/no-file": None},
    )
    monkeypatch.chdir(work)
    found = backlog.remote_id_numbers(Path("docs/BACKLOG.md"))
    # main (SAMPLE) and the pending branches are read; feature/* is ignored; a branch without the file is skipped
    assert {1, 2, 3, 4, 11, 12} <= found
    assert 99 not in found


def test_remote_id_numbers_keeps_only_the_newest_branches(
    backlog, tmp_path, monkeypatch
):
    work = _origin_and_clone(tmp_path, {"backlog/old": 20, "backlog/new": 21})
    monkeypatch.setattr(backlog, "MAX_PENDING_BRANCHES", 1)
    monkeypatch.chdir(work)
    found = backlog.remote_id_numbers(Path("docs/BACKLOG.md"))
    assert found & {20, 21} == {21}


def test_remote_id_numbers_skips_branches_merged_into_the_default_branch(
    backlog, tmp_path, monkeypatch
):
    work = _origin_and_clone(tmp_path, {"backlog/open": 31})
    remote = tmp_path / "remote"
    # a branch that main already contains (a merged, undeleted branch)
    _git(remote, "branch", "backlog/merged", "main")
    _git(work, "fetch", "-q", "origin")
    monkeypatch.setattr(backlog, "MAX_PENDING_BRANCHES", 1)
    monkeypatch.chdir(work)
    # with a window of 1, the merged branch must not push the open one out
    assert 31 in backlog.remote_id_numbers(Path("docs/BACKLOG.md"))


def test_lint_against_reports_ids_used_for_another_item(
    backlog, tmp_path, monkeypatch, capsys
):
    work = _origin_and_clone(tmp_path, {})
    # B-001 is the same item as on origin/main; B-005 is new and B-002 got another title
    text = SAMPLE.replace("### B-002 ", "### B-002 other ")
    path = work / "docs/BACKLOG.md"
    path.write_text(text, encoding="utf-8")
    monkeypatch.chdir(work)
    assert backlog.main(["--file", str(path), "lint"]) == 0
    capsys.readouterr()
    assert backlog.main(["--file", str(path), "lint", "--against", "origin/main"]) == 1
    out = capsys.readouterr().out
    assert "B-002 is used for a different item on origin/main" in out
    assert "B-001" not in out


def test_lint_against_clean_when_titles_match(backlog, tmp_path, monkeypatch, capsys):
    work = _origin_and_clone(tmp_path, {})
    monkeypatch.chdir(work)
    path = work / "docs/BACKLOG.md"
    assert backlog.main(["--file", str(path), "lint", "--against", "origin/main"]) == 0
    assert capsys.readouterr().out == ""


def test_remote_id_numbers_works_from_a_subdirectory_and_with_an_absolute_path(
    backlog, tmp_path, monkeypatch
):
    work = _origin_and_clone(tmp_path, {"backlog/B-030-x": 30})
    monkeypatch.chdir(work / "docs")
    assert 30 in backlog.remote_id_numbers(Path("BACKLOG.md"))
    assert 30 in backlog.remote_id_numbers(work / "docs/BACKLOG.md")


def test_remote_id_numbers_guesses_main_without_origin_head(
    backlog, tmp_path, monkeypatch, capsys
):
    work = _origin_and_clone(tmp_path, {})
    _git(work, "remote", "set-head", "origin", "-d")
    monkeypatch.chdir(work)
    assert {1, 2, 3, 4} <= backlog.remote_id_numbers(Path("docs/BACKLOG.md"))
    assert "origin/HEAD is not set" in capsys.readouterr().err


def test_remote_id_numbers_outside_a_repo_is_empty(
    backlog, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert backlog.remote_id_numbers(Path("docs/BACKLOG.md")) == set()
    assert capsys.readouterr().err == ""


def test_next_id_cli_sees_origin_ids(backlog, tmp_path, monkeypatch, capsys):
    path = write(tmp_path, SAMPLE)
    monkeypatch.setattr(backlog, "remote_id_numbers", lambda p: {40})
    assert backlog.main(["--file", str(path), "next-id"]) == 0
    assert capsys.readouterr().out == "B-041\n"


# --- list ------------------------------------------------------------------


def test_list_order_and_default_filter(backlog):
    out = backlog.render_list(backlog.parse(SAMPLE), None)
    assert out.splitlines() == [
        "B-001  ready  P2  First",
        "B-002  todo  P1  Second  [blocked by B-001]",
        "B-003  todo  P3  Third",
    ]


def test_list_all_includes_archived_items_last(backlog):
    out = backlog.render_list(backlog.parse(SAMPLE), set(backlog.STATES))
    assert out.splitlines()[-1] == "B-004  done  P2  Finished"


def test_list_orders_priority_then_id_within_a_state(backlog):
    text = SAMPLE.replace("- 状態: ready", "- 状態: todo")
    out = backlog.render_list(backlog.parse(text), None)
    assert [line.split("  ")[0] for line in out.splitlines()] == [
        "B-002",
        "B-001",
        "B-003",
    ]


def test_list_marks_blocked_items(backlog):
    # unfinished dependency, dropped dependency, unknown dependency
    done_dep = SAMPLE.replace("- 状態: ready", "- 状態: done")
    assert "[blocked" not in backlog.render_list(backlog.parse(done_dep), None)
    dropped_dep = SAMPLE.replace("- 状態: ready", "- 状態: dropped")
    assert "[blocked by B-001]" in backlog.render_list(backlog.parse(dropped_dep), None)
    unknown = SAMPLE.replace("- 依存: B-001", "- 依存: B-001, B-099")
    assert "[blocked by B-001, B-099]" in backlog.render_list(
        backlog.parse(unknown), None
    )


def test_list_shows_dash_for_missing_priority(backlog):
    text = SAMPLE.replace("- 優先度: P3\n", "")
    assert "B-003  todo  -  Third" in backlog.render_list(backlog.parse(text), None)


def ids(out):
    return [line.split("  ")[0] for line in out.splitlines()]


def test_list_priority_keeps_that_priority_or_higher(backlog):
    bl = backlog.parse(SAMPLE)
    assert ids(backlog.render_list(bl, None, priority="P1")) == ["B-002"]
    assert ids(backlog.render_list(bl, None, priority="P2")) == ["B-001", "B-002"]
    assert ids(backlog.render_list(bl, None, priority="P3")) == [
        "B-001",
        "B-002",
        "B-003",
    ]


def test_list_priority_excludes_items_without_priority(backlog):
    text = SAMPLE.replace("- 優先度: P3\n", "")
    out = backlog.render_list(backlog.parse(text), None, priority="P3")
    assert "B-003" not in out


def test_list_limit_applies_after_sorting_and_priority_filter(backlog):
    bl = backlog.parse(SAMPLE)
    assert backlog.render_list(bl, None, limit=1).splitlines() == [
        "B-001  ready  P2  First"
    ]
    out = backlog.render_list(bl, None, priority="P2", limit=2)
    assert [line.split("  ")[0] for line in out.splitlines()] == ["B-001", "B-002"]
    assert backlog.render_list(bl, None, limit=10).count("\n") == 2


def test_list_exclude_drops_items_before_limit(backlog):
    bl = backlog.parse(SAMPLE)
    assert ids(backlog.render_list(bl, None, exclude={"B-001"})) == ["B-002", "B-003"]
    assert ids(backlog.render_list(bl, None, exclude={"B-001"}, limit=1)) == ["B-002"]
    assert ids(backlog.render_list(bl, None, exclude=set())) == [
        "B-001",
        "B-002",
        "B-003",
    ]


def test_list_unblocked_drops_blocked_items_before_limit(backlog):
    bl = backlog.parse(SAMPLE)
    # B-002 depends on the unfinished B-001, so it is hidden.
    assert ids(backlog.render_list(bl, None, unblocked=True)) == ["B-001", "B-003"]
    # The limit counts after the blocked item is dropped.
    assert ids(backlog.render_list(bl, None, unblocked=True, limit=2)) == [
        "B-001",
        "B-003",
    ]
    assert ids(backlog.render_list(bl, None, priority="P1", unblocked=True)) == []
    # Without the option the blocked item stays (and is marked).
    assert "B-002" in backlog.render_list(bl, None)


def test_list_unblocked_keeps_items_whose_dependency_is_done(backlog):
    done_dep = SAMPLE.replace("- 状態: ready", "- 状態: done")
    out = backlog.render_list(backlog.parse(done_dep), None, unblocked=True)
    assert "B-002" in out


def test_list_unblocked_cli(backlog, tmp_path, capsys):
    path = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(path), "list", "--unblocked"]) == 0
    out = capsys.readouterr().out
    assert [line.split("  ")[0] for line in out.splitlines()] == ["B-001", "B-003"]


def test_started_ids_reads_only_remote_backlog_branches(backlog, tmp_path, monkeypatch):
    import subprocess

    def git(*args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    remote = tmp_path / "remote"
    work = tmp_path / "work"
    remote.mkdir()
    git("init", "-q", "-b", "main", cwd=remote)
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
        cwd=remote,
    )
    git("branch", "backlog/B-031-some-slug", cwd=remote)
    git("branch", "feature/other", cwd=remote)
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True
    )
    git("fetch", "-q", "origin", cwd=work)
    git(
        "branch", "backlog/B-099-local-only", cwd=work
    )  # local-only branches are ignored
    monkeypatch.chdir(work)
    assert backlog.started_ids() == {"B-031"}


def test_started_ids_outside_a_repo_raises(backlog, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(backlog.BacklogError, match="git"):
        backlog.started_ids()


def test_list_not_started_cli(backlog, tmp_path, monkeypatch, capsys):
    path = write(tmp_path, SAMPLE)
    monkeypatch.setattr(backlog, "started_ids", lambda: {"B-001"})
    assert backlog.main(["--file", str(path), "list", "--not-started"]) == 0
    out = capsys.readouterr().out
    assert [line.split("  ")[0] for line in out.splitlines()] == ["B-002", "B-003"]


def test_list_not_started_reports_hidden_ids_on_stderr(
    backlog, tmp_path, monkeypatch, capsys
):
    path = write(tmp_path, SAMPLE)
    monkeypatch.setattr(backlog, "started_ids", lambda: {"B-001"})
    assert backlog.main(["--file", str(path), "list", "--not-started"]) == 0
    captured = capsys.readouterr()
    assert [line.split("  ")[0] for line in captured.out.splitlines()] == [
        "B-002",
        "B-003",
    ]
    assert "hidden by --not-started" in captured.err
    assert "B-001" in captured.err


def test_list_not_started_is_silent_when_nothing_is_hidden(
    backlog, tmp_path, monkeypatch, capsys
):
    path = write(tmp_path, SAMPLE)
    monkeypatch.setattr(backlog, "started_ids", lambda: {"B-999"})
    assert backlog.main(["--file", str(path), "list", "--not-started"]) == 0
    assert capsys.readouterr().err == ""


def _repo_with_backlog(
    tmp_path: Path, committed: str, relpath: str = "docs/BACKLOG.md"
) -> Path:
    import subprocess

    repo = tmp_path / "repo"
    (repo / relpath).parent.mkdir(parents=True)
    (repo / relpath).write_text(committed, encoding="utf-8")
    for args in (
        ["init", "-q", "-b", "main"],
        ["add", "."],
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-q",
            "-m",
            "x",
        ],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


def test_ref_reads_committed_backlog_not_working_tree(
    backlog, tmp_path, monkeypatch, capsys
):
    stale = SAMPLE.replace(
        "- 状態: ready", "- 状態: todo", 1
    )  # the working tree is behind the ref
    repo = _repo_with_backlog(tmp_path, SAMPLE)
    (repo / "docs/BACKLOG.md").write_text(stale, encoding="utf-8")
    monkeypatch.chdir(repo)
    assert backlog.main(["list", "--status", "ready"]) == 0
    assert capsys.readouterr().out == ""
    assert backlog.main(["--ref", "main", "list", "--status", "ready"]) == 0
    assert capsys.readouterr().out.startswith("B-001")
    assert backlog.main(["--ref", "main", "show", "B-001"]) == 0
    assert "decided" in capsys.readouterr().out


def test_ref_rejects_write_commands(backlog, tmp_path, monkeypatch, capsys):
    repo = _repo_with_backlog(tmp_path, SAMPLE)
    monkeypatch.chdir(repo)
    assert backlog.main(["--ref", "main", "set", "B-001", "優先度", "P1"]) == 2
    assert "read-only" in capsys.readouterr().err
    assert backlog.main(["--ref", "main", "archive", "B-001", "--dropped"]) == 2


def test_ref_unknown_ref_fails(backlog, tmp_path, monkeypatch, capsys):
    repo = _repo_with_backlog(tmp_path, SAMPLE)
    monkeypatch.chdir(repo)
    assert backlog.main(["--ref", "origin/nope", "list"]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_list_rejects_invalid_priority_and_limit(backlog):
    bl = backlog.parse(SAMPLE)
    with pytest.raises(backlog.BacklogError):
        backlog.render_list(bl, None, priority="P9")
    with pytest.raises(backlog.BacklogError):
        backlog.render_list(bl, None, limit=0)


# --- show ------------------------------------------------------------------


def test_show_prints_one_item_block(backlog):
    out = backlog.render_show(backlog.parse(SAMPLE), "B-002")
    assert out.splitlines()[0] == "### B-002 Second"
    assert out.splitlines()[-1] == "- 概要: sum"
    assert "B-003" not in out


def test_show_unknown_id_raises(backlog):
    import pytest

    with pytest.raises(backlog.BacklogError, match="B-099"):
        backlog.render_show(backlog.parse(SAMPLE), "B-099")


# --- lint ------------------------------------------------------------------


def lint_text(backlog, text):
    return backlog.lint(backlog.parse(text))


def test_lint_clean_sample(backlog):
    assert lint_text(backlog, SAMPLE) == []


# (id, old, new, message substring, marker of the line the problem points at)
LINT_CASES = [
    (
        "malformed-heading",
        "### B-003 Third",
        "### B-3 Third",
        "malformed",
        "### B-3 Third",
    ),
    (
        "duplicate-id",
        "### B-003 Third",
        "### B-002 Third",
        "duplicate item id B-002",
        "### B-002 Third",
    ),
    (
        "duplicate-field",
        "- 優先度: P3\n",
        "- 優先度: P3\n- 優先度: P2\n",
        "duplicate field 優先度",
        "- 優先度: P2",
    ),
    (
        "missing-added",
        "- 追加: 2026-11-03\n",
        "",
        "B-003: missing 追加",
        "### B-003 Third",
    ),
    (
        "missing-priority",
        "- 優先度: P3\n",
        "",
        "B-003: missing 優先度",
        "### B-003 Third",
    ),
    (
        "invalid-state",
        "- 状態: todo\n- 優先度: P3",
        "- 状態: wip\n- 優先度: P3",
        "invalid 状態",
        "- 状態: wip",
    ),
    (
        "invalid-priority",
        "- 優先度: P3",
        "- 優先度: P9",
        "invalid 優先度",
        "- 優先度: P9",
    ),
    (
        "invalid-date",
        "- 追加: 2026-11-03",
        "- 追加: 11/03",
        "invalid 追加",
        "- 追加: 11/03",
    ),
    (
        "invalid-dependency",
        "- 依存: B-001",
        "- 依存: B-1",
        "invalid 依存",
        "- 依存: B-1",
    ),
    ("invalid-pr", "- PR: #1", "- PR: 1", "invalid PR", "- PR: 1"),
    (
        "ready-without-judgement",
        "- 判断: decided\n",
        "",
        "B-001: missing 判断",
        "### B-001 First",
    ),
    (
        "done-without-completion",
        "- 完了: 2026-10-02\n",
        "",
        "B-004: missing 完了",
        "### B-004 Finished",
    ),
    (
        "dropped-with-pr",
        "- 状態: done\n- 優先度: P2\n- 追加: 2026-10-01\n- 背景: bg\n- 概要: sum\n- 完了: 2026-10-02\n- PR: #1\n",
        "- 状態: dropped\n- 優先度: P2\n- 追加: 2026-10-01\n- 背景: bg\n- 概要: sum\n- 判断: no\n- PR: #1\n",
        "PR must not be set on a dropped item",
        "- PR: #1",
    ),
    (
        "archived-item-in-todo-state",
        "- 状態: done",
        "- 状態: todo",
        "belongs in the 'todo / ready' section",
        "- 状態: todo",
    ),
    (
        "unknown-dependency",
        "- 依存: B-001",
        "- 依存: B-099",
        "unknown dependency B-099",
        "- 依存: B-099",
    ),
    (
        "dependency-cycle",
        "- 状態: ready\n- 優先度: P2\n",
        "- 状態: ready\n- 優先度: P2\n- 依存: B-002\n",
        "dependency cycle",
        "- 依存: B-002",
    ),
]


@pytest.mark.parametrize(
    "name,old,new,message,marker", LINT_CASES, ids=[c[0] for c in LINT_CASES]
)
def test_lint_detects(backlog, name, old, new, message, marker):
    text = SAMPLE.replace(old, new, 1)
    assert text != SAMPLE
    problems = lint_text(backlog, text)
    assert len(problems) == 1, problems
    assert message in problems[0].message
    marker_lines = [n + 1 for n, line in enumerate(text.split("\n")) if line == marker]
    assert problems[0].line in marker_lines


def test_lint_unknown_dependency_is_reported_not_just_blocked(backlog):
    # Review focus: a dependency that does not exist is an error, not only a "blocked" mark.
    text = SAMPLE.replace("- 依存: B-001", "- 依存: B-099")
    assert any(
        "unknown dependency B-099" in p.message for p in lint_text(backlog, text)
    )


def test_lint_dependency_cycle_is_reported_once(backlog):
    text = SAMPLE.replace(
        "- 状態: ready\n- 優先度: P2\n",
        "- 状態: ready\n- 優先度: P2\n- 依存: B-002\n",
        1,
    )
    cycles = [p for p in lint_text(backlog, text) if "cycle" in p.message]
    assert (
        len(cycles) == 1
        and "B-001" in cycles[0].message
        and "B-002" in cycles[0].message
    )


def test_cli_lint_exit_codes_and_format(backlog, tmp_path, capsys):
    clean = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(clean), "lint"]) == 0
    assert capsys.readouterr().out == ""
    bad = write(tmp_path, SAMPLE.replace("- 優先度: P3\n", "", 1))
    assert backlog.main(["--file", str(bad), "lint"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith(f"{bad}:")
    assert "B-003: missing 優先度" in out[0]


# --- set -------------------------------------------------------------------


def changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    old, new = before.split("\n"), after.split("\n")
    assert len(old) == len(new)
    return [(a, b) for a, b in zip(old, new) if a != b]


def test_write_checked_keeps_mode_and_leaves_no_temp_file(backlog, tmp_path):
    path = write(tmp_path, SAMPLE)
    path.chmod(0o640)
    backlog.write_checked(
        path, SAMPLE, backlog.set_field(SAMPLE, "B-002", "優先度", "P2")
    )
    assert "- 優先度: P2" in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o7777 == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["BACKLOG.md"]


def test_write_checked_writes_through_a_symlink(backlog, tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = write(real_dir, SAMPLE)
    link = tmp_path / "link.md"
    link.symlink_to(real)
    backlog.write_checked(
        link, SAMPLE, backlog.set_field(SAMPLE, "B-002", "優先度", "P2")
    )
    assert link.is_symlink()
    assert "- 優先度: P2" in real.read_text(encoding="utf-8")
    assert sorted(p.name for p in real_dir.iterdir()) == ["BACKLOG.md"]


def test_write_checked_failure_keeps_the_original(backlog, tmp_path, monkeypatch):
    path = write(tmp_path, SAMPLE)

    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(backlog.BacklogError, match="cannot write"):
        backlog.write_checked(
            path, SAMPLE, backlog.set_field(SAMPLE, "B-002", "優先度", "P2")
        )
    assert path.read_text(encoding="utf-8") == SAMPLE
    assert [p.name for p in tmp_path.iterdir()] == ["BACKLOG.md"]


def test_set_replaces_only_that_line(backlog):
    out = backlog.set_field(SAMPLE, "B-002", "優先度", "P2")
    assert changed_lines(SAMPLE, out) == [("- 優先度: P1", "- 優先度: P2")]


def test_set_inserts_missing_field_in_order(backlog):
    out = backlog.set_field(SAMPLE, "B-003", "依存", "B-001")
    lines = out.split("\n")
    at = lines.index("- 依存: B-001", lines.index("### B-003 Third"))
    assert lines[at - 1] == "- 優先度: P3" and lines[at + 1] == "- 追加: 2026-11-03"
    assert len(lines) == len(SAMPLE.split("\n")) + 1

    no_priority = SAMPLE.replace("- 優先度: P3\n", "", 1)
    lines = backlog.set_field(no_priority, "B-003", "優先度", "P1").split("\n")
    at = lines.index("- 優先度: P1", lines.index("### B-003 Third"))
    assert lines[at - 1] == "- 状態: todo" and lines[at + 1] == "- 追加: 2026-11-03"


@pytest.mark.parametrize(
    "item,key,value,message",
    [
        (
            "B-002",
            "優先度",
            "P1\n- 状態: done",
            "newline",
        ),  # Review focus: a value must stay on one line
        ("B-099", "優先度", "P1", "B-099"),
        ("B-002", "背景", "x", "cannot set"),
        ("B-002", "優先度", "P9", "P1, P2, P3"),
        ("B-002", "状態", "wip", "todo, ready"),
        ("B-002", "状態", "done", "archive"),
        ("B-002", "状態", "dropped", "archive"),
        ("B-004", "状態", "todo", "archived"),
    ],
)
def test_set_rejects(backlog, item, key, value, message):
    with pytest.raises(backlog.BacklogError, match=message):
        backlog.set_field(SAMPLE, item, key, value)


# --- archive ---------------------------------------------------------------

TODAY = date(2026, 11, 22)


def test_archive_done_moves_block_and_adds_completion_fields(backlog):
    out = backlog.archive_item(SAMPLE, "B-001", "done", 7, TODAY)
    bl = backlog.parse(out)
    moved = next(i for i in bl.items if i.id == "B-001")
    assert moved.section == backlog.SECTION_ARCHIVE
    assert [i.id for i in bl.items] == ["B-002", "B-003", "B-004", "B-001"]
    assert (moved.get("状態"), moved.get("完了"), moved.get("PR")) == (
        "done",
        "2026-11-22",
        "#7",
    )
    assert moved.get("判断") == "decided"
    assert backlog.lint(bl) == []


def test_archive_leaves_other_text_untouched(backlog):
    block = backlog.render_show(backlog.parse(SAMPLE), "B-001") + "\n\n"
    out = backlog.archive_item(SAMPLE, "B-001", "done", 7, TODAY)
    assert out.startswith(SAMPLE.replace(block, "", 1))
    assert out.endswith("\n") and not out.endswith("\n\n")


def test_archive_dropped_requires_judgement(backlog):
    with pytest.raises(backlog.BacklogError, match="判断"):
        backlog.archive_item(SAMPLE, "B-003", "dropped", None, TODAY)
    out = backlog.archive_item(SAMPLE, "B-001", "dropped", None, TODAY)
    moved = next(i for i in backlog.parse(out).items if i.id == "B-001")
    assert moved.get("状態") == "dropped" and moved.get("PR") is None
    assert backlog.lint(backlog.parse(out)) == []


def test_archive_into_empty_section_removes_placeholder(backlog):
    # Review focus: an empty archive section holds a "（なし）" placeholder.
    block = backlog.render_show(backlog.parse(SAMPLE), "B-004") + "\n"
    empty = SAMPLE.replace(block, "（なし）\n", 1)
    assert "（なし）" in empty
    out = backlog.archive_item(empty, "B-001", "done", 7, TODAY)
    assert "（なし）" not in out
    assert out.count("## done / dropped\n\n### B-001 First\n") == 1
    assert backlog.lint(backlog.parse(out)) == []


def test_archive_done_without_pr_writes_no_pr(backlog):
    out = backlog.archive_item(SAMPLE, "B-001", "done", None, TODAY)
    moved = backlog.find_item(backlog.parse(out), "B-001")
    assert moved.get("状態") == "done" and moved.get("PR") is None
    assert moved.get("完了") == TODAY.isoformat()
    assert backlog.lint(backlog.parse(out)) == []


def test_archive_inserts_before_the_next_section(backlog):
    text = SAMPLE + "\n## Appendix\n\nnotes\n"
    out = backlog.archive_item(text, "B-001", "done", 7, TODAY)
    assert out.endswith("- PR: #7\n\n## Appendix\n\nnotes\n")
    assert backlog.lint(backlog.parse(out)) == []


@pytest.mark.parametrize(
    "item,outcome,pr,message",
    [
        ("B-001", "dropped", 7, "--pr"),
        ("B-004", "done", 7, "already"),
        ("B-099", "done", 7, "B-099"),
        ("B-001", "wip", None, "done or dropped"),
    ],
)
def test_archive_rejects(backlog, item, outcome, pr, message):
    with pytest.raises(backlog.BacklogError, match=message):
        backlog.archive_item(SAMPLE, item, outcome, pr, TODAY)


# --- CLI: set / archive ----------------------------------------------------


def test_cli_set_writes_file(backlog, tmp_path):
    path = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(path), "set", "B-003", "優先度", "P1"]) == 0
    assert path.read_text(encoding="utf-8") == backlog.set_field(
        SAMPLE, "B-003", "優先度", "P1"
    )


def test_cli_set_does_not_write_when_it_would_introduce_a_lint_problem(
    backlog, tmp_path, capsys
):
    path = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(path), "set", "B-003", "依存", "B-099"]) == 2
    assert "unknown dependency B-099" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == SAMPLE


def test_cli_set_ignores_problems_that_were_already_there(backlog, tmp_path):
    broken = SAMPLE.replace("- 完了: 2026-10-02\n", "", 1)
    path = write(tmp_path, broken)
    assert backlog.main(["--file", str(path), "set", "B-003", "優先度", "P1"]) == 0


def test_cli_set_error_leaves_file_untouched(backlog, tmp_path, capsys):
    path = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(path), "set", "B-002", "優先度", "P1\nx"]) == 2
    assert "newline" in capsys.readouterr().err
    assert backlog.main(["--file", str(path), "set", "B-099", "優先度", "P1"]) == 2
    assert path.read_text(encoding="utf-8") == SAMPLE


def test_cli_archive(backlog, tmp_path):
    path = write(tmp_path, SAMPLE)
    assert (
        backlog.main(["--file", str(path), "archive", "B-001", "--done", "--pr", "7"])
        == 0
    )
    text = path.read_text(encoding="utf-8")
    assert f"- 完了: {date.today().isoformat()}" in text and "- PR: #7" in text
    assert backlog.lint(backlog.parse(text)) == []
    assert (
        backlog.main(["--file", str(path), "archive", "B-002", "--dropped"]) == 2
    )  # no 判断 yet


# --- the real backlog ------------------------------------------------------


def real_backlog(backlog):
    return backlog.parse((ROOT / "docs" / "BACKLOG.md").read_text(encoding="utf-8"))


def test_real_backlog_is_clean(backlog):
    assert backlog.lint(real_backlog(backlog)) == []


def test_real_backlog_has_priorities_and_known_dependencies(backlog):
    items = {i.id: i for i in real_backlog(backlog).items}
    for item in items.values():
        if item.get("状態") in ("todo", "ready"):
            assert item.get("優先度") in backlog.PRIORITIES, item.id
    assert items["B-010"].get("依存") == "B-009"
    assert items["B-012"].get("依存") == "B-011"
    assert items["B-014"].get("依存") == "B-011, B-012"
    assert "B-022" in items


# --- CLI -------------------------------------------------------------------


def test_cli_list_and_next_id(backlog, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(backlog, "remote_id_numbers", lambda path: set())
    path = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(path), "list"]) == 0
    assert capsys.readouterr().out.startswith("B-001  ready  P2  First\n")
    assert backlog.main(["--file", str(path), "list", "--status", "done"]) == 0
    assert capsys.readouterr().out == "B-004  done  P2  Finished\n"
    assert backlog.main(["--file", str(path), "next-id"]) == 0
    assert capsys.readouterr().out == "B-005\n"
    assert backlog.main(["--file", str(path), "show", "B-003"]) == 0
    assert capsys.readouterr().out.startswith("### B-003 Third\n")


def test_cli_list_priority_and_limit(backlog, tmp_path, capsys):
    path = write(tmp_path, SAMPLE)
    assert (
        backlog.main(["--file", str(path), "list", "--priority", "P2", "--limit", "1"])
        == 0
    )
    assert capsys.readouterr().out == "B-001  ready  P2  First\n"
    assert backlog.main(["--file", str(path), "list", "--priority", "P9"]) == 2
    assert "P9" in capsys.readouterr().err


def test_cli_list_rejects_invalid_status(backlog, tmp_path, capsys):
    path = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(path), "list", "--status", "Todo"]) == 2
    assert "invalid status 'Todo'" in capsys.readouterr().err
    # Every comma-separated value is checked.
    assert backlog.main(["--file", str(path), "list", "--status", "ready,bogus"]) == 2
    assert "bogus" in capsys.readouterr().err
    assert backlog.main(["--file", str(path), "list", "--status", "ready,todo"]) == 0


def test_cli_missing_file_exits_2(backlog, tmp_path, capsys):
    missing = tmp_path / "nope.md"
    assert backlog.main(["--file", str(missing), "list"]) == 2
    captured = capsys.readouterr()
    assert str(missing) in captured.err
    assert "Traceback" not in captured.err


def test_cli_empty_file_lists_nothing(backlog, tmp_path, capsys):
    path = write(tmp_path, "")
    assert backlog.main(["--file", str(path), "list"]) == 0
    assert capsys.readouterr().out == ""


def test_script_is_executable():
    assert os.access(ROOT / "shared" / "backlog" / "backlog.py", os.X_OK)


def test_default_file_is_found_from_a_subdirectory(
    backlog, tmp_path, monkeypatch, capsys
):
    repo = _repo_with_backlog(tmp_path, SAMPLE)
    sub = repo / "plugins" / "x"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert backlog.main(["show", "B-001"]) == 0
    assert "B-001" in capsys.readouterr().out
    assert backlog.main(["--ref", "main", "show", "B-001"]) == 0


def test_default_file_search_stops_at_the_git_root(
    backlog, tmp_path, monkeypatch, capsys
):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/BACKLOG.md").write_text(SAMPLE, encoding="utf-8")
    inner = tmp_path / "inner"
    (inner / "sub").mkdir(parents=True)
    _git(inner, "init", "-q", "-b", "main")
    monkeypatch.chdir(inner / "sub")
    assert backlog.main(["list"]) == 2
    err = capsys.readouterr().err
    assert str(inner / "sub") in err


def test_default_file_outside_a_repo_is_cwd_relative(
    backlog, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)
    assert backlog.main(["list"]) == 2
    assert str(tmp_path) in capsys.readouterr().err
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/BACKLOG.md").write_text(SAMPLE, encoding="utf-8")
    assert backlog.main(["show", "B-001"]) == 0


def test_explicit_file_is_not_searched(backlog, tmp_path, monkeypatch, capsys):
    repo = _repo_with_backlog(tmp_path, SAMPLE)
    sub = repo / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert backlog.main(["--file", "docs/BACKLOG.md", "list"]) == 2
    assert backlog.main(["--file", str(repo / "docs/BACKLOG.md"), "list"]) == 0
