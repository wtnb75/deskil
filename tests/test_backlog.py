"""Tests for shared/backlog/backlog.py."""

import os
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
    assert [line.split("  ")[0] for line in out.splitlines()] == ["B-002", "B-001", "B-003"]


def test_list_marks_blocked_items(backlog):
    # unfinished dependency, dropped dependency, unknown dependency
    done_dep = SAMPLE.replace("- 状態: ready", "- 状態: done")
    assert "[blocked" not in backlog.render_list(backlog.parse(done_dep), None)
    dropped_dep = SAMPLE.replace("- 状態: ready", "- 状態: dropped")
    assert "[blocked by B-001]" in backlog.render_list(backlog.parse(dropped_dep), None)
    unknown = SAMPLE.replace("- 依存: B-001", "- 依存: B-001, B-099")
    assert "[blocked by B-001, B-099]" in backlog.render_list(backlog.parse(unknown), None)


def test_list_shows_dash_for_missing_priority(backlog):
    text = SAMPLE.replace("- 優先度: P3\n", "")
    assert "B-003  todo  -  Third" in backlog.render_list(backlog.parse(text), None)


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
    ("malformed-heading", "### B-003 Third", "### B-3 Third", "malformed", "### B-3 Third"),
    ("duplicate-id", "### B-003 Third", "### B-002 Third", "duplicate item id B-002", "### B-002 Third"),
    ("duplicate-field", "- 優先度: P3\n", "- 優先度: P3\n- 優先度: P2\n", "duplicate field 優先度", "- 優先度: P2"),
    ("missing-added", "- 追加: 2026-11-03\n", "", "B-003: missing 追加", "### B-003 Third"),
    ("missing-priority", "- 優先度: P3\n", "", "B-003: missing 優先度", "### B-003 Third"),
    ("invalid-state", "- 状態: todo\n- 優先度: P3", "- 状態: wip\n- 優先度: P3", "invalid 状態", "- 状態: wip"),
    ("invalid-priority", "- 優先度: P3", "- 優先度: P9", "invalid 優先度", "- 優先度: P9"),
    ("invalid-date", "- 追加: 2026-11-03", "- 追加: 11/03", "invalid 追加", "- 追加: 11/03"),
    ("invalid-dependency", "- 依存: B-001", "- 依存: B-1", "invalid 依存", "- 依存: B-1"),
    ("invalid-pr", "- PR: #1", "- PR: 1", "invalid PR", "- PR: 1"),
    ("ready-without-judgement", "- 判断: decided\n", "", "B-001: missing 判断", "### B-001 First"),
    ("done-without-completion", "- 完了: 2026-10-02\n", "", "B-004: missing 完了", "### B-004 Finished"),
    ("done-without-pr", "- PR: #1\n", "", "B-004: missing PR", "### B-004 Finished"),
    (
        "dropped-with-pr",
        "- 状態: done\n- 優先度: P2\n- 追加: 2026-10-01\n- 背景: bg\n- 概要: sum\n- 完了: 2026-10-02\n- PR: #1\n",
        "- 状態: dropped\n- 優先度: P2\n- 追加: 2026-10-01\n- 背景: bg\n- 概要: sum\n- 判断: no\n- PR: #1\n",
        "PR must not be set on a dropped item",
        "- PR: #1",
    ),
    ("archived-item-in-todo-state", "- 状態: done", "- 状態: todo", "belongs in the 'todo / ready' section", "- 状態: todo"),
    ("unknown-dependency", "- 依存: B-001", "- 依存: B-099", "unknown dependency B-099", "- 依存: B-099"),
    (
        "dependency-cycle",
        "- 状態: ready\n- 優先度: P2\n",
        "- 状態: ready\n- 優先度: P2\n- 依存: B-002\n",
        "dependency cycle",
        "- 依存: B-002",
    ),
]


@pytest.mark.parametrize("name,old,new,message,marker", LINT_CASES, ids=[c[0] for c in LINT_CASES])
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
    assert any("unknown dependency B-099" in p.message for p in lint_text(backlog, text))


def test_lint_dependency_cycle_is_reported_once(backlog):
    text = SAMPLE.replace("- 状態: ready\n- 優先度: P2\n", "- 状態: ready\n- 優先度: P2\n- 依存: B-002\n", 1)
    cycles = [p for p in lint_text(backlog, text) if "cycle" in p.message]
    assert len(cycles) == 1 and "B-001" in cycles[0].message and "B-002" in cycles[0].message


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


# --- CLI -------------------------------------------------------------------


def test_cli_list_and_next_id(backlog, tmp_path, capsys):
    path = write(tmp_path, SAMPLE)
    assert backlog.main(["--file", str(path), "list"]) == 0
    assert capsys.readouterr().out.startswith("B-001  ready  P2  First\n")
    assert backlog.main(["--file", str(path), "list", "--status", "done"]) == 0
    assert capsys.readouterr().out == "B-004  done  P2  Finished\n"
    assert backlog.main(["--file", str(path), "next-id"]) == 0
    assert capsys.readouterr().out == "B-005\n"
    assert backlog.main(["--file", str(path), "show", "B-003"]) == 0
    assert capsys.readouterr().out.startswith("### B-003 Third\n")


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
