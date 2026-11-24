"""Tests for the `timeline` subcommand."""

import json
import os
import stat
from pathlib import Path

import pytest
import usage


def _write_run(d: Path, run_id: str, history=None, status="ended", current="end"):
    data = {
        "run_id": run_id,
        "definition": "flow.toml",
        "definition_hash": "h",
        "current": current,
        "visits": {"a": 1},
        "history": history or [],
        "status": status,
        "session_id": "s-" + run_id,
        "started_at": "2026-01-01T00:00:00.000+00:00",
    }
    (d / f"{run_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _usage_data(run_id: str, tokens: int = 100) -> dict:
    return {
        "run_id": run_id,
        "states": {},
        "timeline": [
            {
                "state": "a",
                "visit": 1,
                "start": "2026-01-01T00:00:00.000+00:00",
                "end": "2026-01-01T00:01:00.000+00:00",
                "gate": False,
                "open": False,
                "input": tokens,
                "cache_create": 0,
                "cache_read": 0,
                "output": 0,
                "turns": 1,
                "tool_calls": 0,
                "sub_total": 0,
                "agents": [],
            }
        ],
    }


@pytest.fixture(autouse=True)
def _no_session_logs(monkeypatch):
    # Default: no session log is found, so the saved usage.json / history is used.
    real = usage.compute_usage
    monkeypatch.setattr(
        usage,
        "compute_usage",
        lambda **kw: real(projects_dir=Path("/nonexistent"), **kw),
    )


def _setup(d: Path, ids=("r1", "r2")) -> None:
    for rid in ids:
        _write_run(d, rid)
        usage.save_usage(d, rid, _usage_data(rid))


def test_timeline_writes_html_and_prints_path(flow, tmp_path, capsys):
    _setup(tmp_path)
    out = tmp_path / "out.html"
    args = ["timeline", "r1", "r2", "-o", str(out), "--state-dir", str(tmp_path)]
    assert flow.main(args) == 0
    html = out.read_text("utf-8")
    assert html.startswith("<!doctype html>")
    assert "r1" in html and "r2" in html
    assert capsys.readouterr().out == f"{out}\n"


def test_timeline_output_dash_prints_html(flow, tmp_path, capsys):
    _setup(tmp_path, ("r1",))
    assert flow.main(["timeline", "r1", "-o", "-", "--state-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("<!doctype html>")


def test_timeline_json_prints_views(flow, tmp_path, capsys):
    _setup(tmp_path)
    out = tmp_path / "never.html"
    args = [
        "timeline",
        "r1",
        "r2",
        "--json",
        "-o",
        str(out),
        "--state-dir",
        str(tmp_path),
    ]
    assert flow.main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in data["runs"]] == ["r1", "r2"]
    assert data["runs"][0]["visits"][0]["tok"] == 100
    assert not out.exists()


def test_timeline_falls_back_to_history_without_log_or_usage_json(
    flow, tmp_path, capsys
):
    history = [
        {"state": "a", "label": "ok", "at": "2026-01-01T00:02:00.000+00:00"},
    ]
    _write_run(tmp_path, "r1", history=history)
    assert flow.main(["timeline", "r1", "--json", "--state-dir", str(tmp_path)]) == 0
    visits = json.loads(capsys.readouterr().out)["runs"][0]["visits"]
    assert len(visits) >= 1
    assert all(v["known"] is False for v in visits)


def test_timeline_prefers_computed_over_saved(flow, tmp_path, monkeypatch, capsys):
    _setup(tmp_path, ("r1",))
    monkeypatch.setattr(usage, "compute_usage", lambda **kw: _usage_data("r1", 777))
    assert flow.main(["timeline", "r1", "--json", "--state-dir", str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["runs"][0]["visits"][0]["tok"] == 777


def test_timeline_unknown_run_exits_1(flow, tmp_path, capsys):
    assert flow.main(["timeline", "nope", "--state-dir", str(tmp_path)]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_timeline_unwritable_output_is_an_error_line(flow, tmp_path, capsys):
    _setup(tmp_path, ("r1",))
    out = tmp_path / "missing-dir" / "out.html"
    args = ["timeline", "r1", "-o", str(out), "--state-dir", str(tmp_path)]
    assert flow.main(args) == 1
    assert capsys.readouterr().err.startswith("error: cannot write")


def test_timeline_open_flag_calls_webbrowser_and_ignores_failure(
    flow, tmp_path, monkeypatch, capsys
):
    import webbrowser

    _setup(tmp_path, ("r1",))
    seen = []

    def boom(url):
        seen.append(url)
        raise RuntimeError("no browser")

    monkeypatch.setattr(webbrowser, "open", boom)
    out = tmp_path / "out.html"
    args = ["timeline", "r1", "--open", "-o", str(out), "--state-dir", str(tmp_path)]
    assert flow.main(args) == 0
    assert seen == [out.resolve().as_uri()]


def test_timeline_output_file_is_private_and_replaces_content(flow, tmp_path):
    _setup(tmp_path, ("r1",))
    out = tmp_path / "out.html"
    out.write_text("old content that is much longer than nothing" * 500)
    out.chmod(0o644)
    args = ["timeline", "r1", "-o", str(out), "--state-dir", str(tmp_path)]
    assert flow.main(args) == 0
    assert out.read_text("utf-8").startswith("<!doctype html>")
    assert "old content" not in out.read_text("utf-8")
    fresh = tmp_path / "fresh.html"
    args = ["timeline", "r1", "-o", str(fresh), "--state-dir", str(tmp_path)]
    assert flow.main(args) == 0
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o600


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="needs O_NOFOLLOW")
def test_timeline_refuses_a_symlink_at_the_output_path(flow, tmp_path, capsys):
    _setup(tmp_path, ("r1",))
    target = tmp_path / "target.txt"
    target.write_text("keep")
    link = tmp_path / "link.html"
    link.symlink_to(target)
    args = ["timeline", "r1", "-o", str(link), "--state-dir", str(tmp_path)]
    assert flow.main(args) == 1
    assert capsys.readouterr().err.startswith("error: cannot write")
    assert target.read_text() == "keep"


def test_timeline_json_never_contains_non_finite_numbers(
    flow, tmp_path, monkeypatch, capsys
):
    _setup(tmp_path, ("r1",))
    data = _usage_data("r1", float("nan"))
    monkeypatch.setattr(usage, "compute_usage", lambda **kw: data)
    assert flow.main(["timeline", "r1", "--json", "--state-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "NaN" not in out
    assert json.loads(out)["runs"][0]["visits"][0]["known"] is False
