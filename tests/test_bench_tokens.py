import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "shared" / "bench" / "tokens.py"
_spec = importlib.util.spec_from_file_location("bench_tokens", _PATH)
tokens = importlib.util.module_from_spec(_spec)
sys.modules["bench_tokens"] = tokens
_spec.loader.exec_module(tokens)


def usage(i, c, r, o):
    return {
        "input_tokens": i,
        "cache_creation_input_tokens": c,
        "cache_read_input_tokens": r,
        "output_tokens": o,
    }


def assistant(mid, u, blocks):
    return {"type": "assistant", "message": {"id": mid, "usage": u, "content": blocks}}


def user(blocks):
    return {"type": "user", "message": {"content": blocks}}


def write_log(path: Path, entries, junk=False):
    lines = [json.dumps(e) for e in entries]
    if junk:
        lines.insert(1, "not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def log(tmp_path):
    return write_log(
        tmp_path / "a.jsonl",
        [
            {"type": "system"},
            # one message written as two lines: counted once, with the last usage
            assistant("m1", usage(2, 10, 100, 5), [{"type": "text", "text": "x"}]),
            assistant("m1", usage(2, 10, 100, 7), [{"type": "tool_use", "id": "t1"}]),
            user([{"type": "tool_result", "tool_use_id": "t1", "is_error": True}]),
            assistant("m2", usage(1, 0, 120, 3), [{"type": "tool_use", "id": "t2"}]),
            user(
                [
                    {"type": "tool_result", "tool_use_id": "t2"},
                    {"type": "text", "text": "hi"},
                ]
            ),
        ],
        junk=True,
    )


def test_collect_counts_each_message_once(log):
    s = tokens.collect(log)
    assert (s.input, s.cache_create, s.cache_read, s.output) == (3, 10, 220, 10)
    assert s.total == 243
    assert s.turns == 2


def test_collect_counts_tools_and_errors(log):
    s = tokens.collect(log)
    assert s.tool_calls == 2
    assert s.tool_errors == 1


def test_collect_ignores_string_content(tmp_path):
    path = write_log(
        tmp_path / "b.jsonl", [{"type": "user", "message": {"content": "hello"}}]
    )
    assert tokens.collect(path) == tokens.Stats()


def test_parse_targets_requires_label():
    assert tokens.parse_targets(["plain=a.jsonl"]) == [("plain", Path("a.jsonl"))]
    for bad in ("a.jsonl", "=a.jsonl", "plain="):
        with pytest.raises(ValueError):
            tokens.parse_targets([bad])


def test_collect_tolerates_odd_entries(tmp_path):
    path = write_log(
        tmp_path / "c.jsonl",
        [
            None,
            [1],
            assistant("m1", {"input_tokens": None, "output_tokens": 4}, []),
            assistant(None, usage(9, 9, 9, 9), []),  # no id: not an API response
        ],
    )
    s = tokens.collect(path)
    assert (s.input, s.output, s.turns) == (0, 4, 1)


def test_group_means():
    p = Path("x")
    a = tokens.Stats(output=10, turns=2)
    b = tokens.Stats(output=20, turns=4)
    means = tokens.group_means([("plain", p, a), ("plain", p, b), ("deskil", p, a)])
    assert means["plain"][tokens.COLUMNS.index("output")] == 15
    assert means["deskil"][tokens.COLUMNS.index("turns")] == 2


def test_main_table_and_json(log, capsys):
    assert tokens.main([f"plain={log}", f"deskil={log}"]) == 0
    out = capsys.readouterr().out
    assert "mean:plain" in out and "mean:deskil" in out
    assert tokens.main(["--json", f"plain={log}"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["runs"][0]["total"] == 243
    assert data["means"]["plain"]["tool_errors"] == 1


def test_main_reports_errors(tmp_path, capsys):
    assert tokens.main(["nolabel"]) == 1
    assert tokens.main([f"x={tmp_path / 'missing.jsonl'}"]) == 1
    assert "error:" in capsys.readouterr().err


def test_declares_python_version_for_uv_run():
    text = _PATH.read_text(encoding="utf-8")
    assert text.startswith(
        '#!/usr/bin/env python3\n# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\n'
    )
