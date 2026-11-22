"""Tests for shared/backlog/backlog.py."""

import os
from pathlib import Path

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
