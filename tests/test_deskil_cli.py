"""The `deskil` entry point: it dispatches `deskil flow …` to the flow engine."""

import deskil
import pytest


@pytest.fixture
def good(flow, write_def, tmp_path):
    return write_def(tmp_path, flow.NEW_TEMPLATE)


@pytest.fixture
def bad(write_def, tmp_path):
    return write_def(tmp_path, 'schema = 1\nstart = "nowhere"\n[states]\n', "bad.toml")


@pytest.fixture(autouse=True)
def no_flow_cmd(monkeypatch):
    monkeypatch.delenv("FLOW_CMD", raising=False)


def test_version(capsys):
    assert deskil.main(["--version"]) == 0
    assert capsys.readouterr().out == "deskil 1.0.0\n"


def test_no_args_prints_usage(capsys):
    assert deskil.main([]) == 2
    err = capsys.readouterr().err
    assert "usage: deskil" in err and "flow" in err


def test_unknown_command(capsys):
    assert deskil.main(["nope"]) == 2
    assert "unknown command: nope" in capsys.readouterr().err


def test_help_exits_zero(capsys):
    assert deskil.main(["--help"]) == 0
    assert "flow" in capsys.readouterr().out


@pytest.mark.parametrize("which", ["good", "bad"])
def test_flow_is_passed_through(flow, capsys, request, which):
    path = str(request.getfixturevalue(which))
    expected = flow.main(["lint", path])
    want = capsys.readouterr()
    assert deskil.main(["flow", "lint", path]) == expected
    got = capsys.readouterr()
    assert (got.out, got.err) == (want.out, want.err)
    assert (expected == 0) == (which == "good")


def test_flow_help_uses_the_deskil_prog(capsys):
    with pytest.raises(SystemExit) as e:
        deskil.main(["flow", "--help"])
    assert e.value.code == 0
    assert capsys.readouterr().out.startswith("usage: deskil flow")


def test_next_hint_is_deskil_flow(good, tmp_path, capsys):
    assert (
        deskil.main(["flow", "start", str(good), "--state-dir", str(tmp_path / "r")])
        == 0
    )
    out = capsys.readouterr().out
    assert "deskil flow next " in out
    assert "uv run" not in out


def test_flow_cmd_env_wins(good, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FLOW_CMD", "custom")
    assert (
        deskil.main(["flow", "start", str(good), "--state-dir", str(tmp_path / "r")])
        == 0
    )
    assert "custom next " in capsys.readouterr().out
