"""Tests for the `usage` subcommand."""

import json
from pathlib import Path

import usage


def _write_run(d: Path, run_id: str) -> None:
    data = {
        "run_id": run_id,
        "definition": "flow.toml",
        "definition_hash": "h",
        "current": "end",
        "visits": {"a": 1},
        "history": [],
        "status": "done",
        "session_id": "s-" + run_id,
        "started_at": "2026-01-01T00:00:00Z",
    }
    (d / f"{run_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _usage_data(run_id: str, a_out: int) -> dict:
    return {
        "run_id": run_id,
        "states": {
            "a": {
                "visits": 1,
                "input": 10,
                "cache_create": 20,
                "cache_read": 30,
                "output": a_out,
                "turns": 1,
                "tool_calls": 0,
                "sub_total": 0,
            }
        },
    }


def _setup(tmp_path: Path, ids=("r1", "r2")) -> Path:
    for i, rid in enumerate(ids):
        _write_run(tmp_path, rid)
        usage.save_usage(tmp_path, rid, _usage_data(rid, 40 + i * 100))
    return tmp_path


def test_usage_command_two_runs_prints_table(flow, tmp_path, capsys):
    d = _setup(tmp_path)
    assert flow.main(["usage", "r1", "r2", "--state-dir", str(d)]) == 0
    out = capsys.readouterr().out
    # totals are 100 and 200 -> mean 150.0
    assert "150" in out
    assert "state" in out
    assert "a" in out


def test_usage_command_json_has_per_run(flow, tmp_path, capsys):
    d = _setup(tmp_path)
    assert flow.main(["usage", "r1", "r2", "--json", "--state-dir", str(d)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["runs"] == 2
    assert data["states"]["a"]["total_mean"] == 150
    assert set(data["per_run"]) == {"r1", "r2"}
    assert data["per_run"]["r1"]["states"]["a"]["output"] == 40


def test_usage_unknown_run_exits_1(flow, tmp_path, capsys):
    assert flow.main(["usage", "nope", "--state-dir", str(tmp_path)]) == 1
    assert "error: run not found: nope" in capsys.readouterr().err


def test_usage_without_any_data_names_the_run(flow, tmp_path, capsys):
    _write_run(tmp_path, "r1")
    assert flow.main(["usage", "r1", "--state-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "no usage data for run r1" in err


def test_usage_save_writes_usage_json(flow, tmp_path, monkeypatch, capsys):
    _write_run(tmp_path, "r1")
    monkeypatch.setattr(usage, "compute_usage", lambda **kw: _usage_data("r1", 40))
    assert flow.main(["usage", "r1", "--save", "--state-dir", str(tmp_path)]) == 0
    saved = json.loads((tmp_path / "r1" / "usage.json").read_text("utf-8"))
    assert saved["states"]["a"]["output"] == 40


def test_usage_without_save_does_not_write(flow, tmp_path, monkeypatch, capsys):
    _write_run(tmp_path, "r1")
    monkeypatch.setattr(usage, "compute_usage", lambda **kw: _usage_data("r1", 40))
    assert flow.main(["usage", "r1", "--state-dir", str(tmp_path)]) == 0
    assert not (tmp_path / "r1" / "usage.json").exists()
