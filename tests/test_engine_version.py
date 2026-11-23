"""The engine version and the `engine` minimum-version key of a definition."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def defn(flow, write_def, tmp_path):
    """Write the template definition with an extra top-level line; return its path."""

    def _make(line: str = "") -> Path:
        text = flow.NEW_TEMPLATE
        if line:
            text = line + "\n" + text
        return write_def(tmp_path, text)

    return _make


def test_version_is_semver(flow):
    assert flow.__version__ == "1.0.0"


@pytest.mark.parametrize("value", ['">=1.0"', '">=1.0.0"', '">= 0.9"'])
def test_engine_satisfied_lints_clean(flow, defn, value):
    assert flow.lint(defn(f"engine = {value}")) == []


def test_engine_missing_is_fine(flow, defn):
    assert flow.lint(defn()) == []


@pytest.mark.parametrize("cmd", ["lint", "dry-run", "graph", "export", "fmt", "start"])
def test_engine_too_new_stops_the_command(flow, defn, tmp_path, capsys, cmd):
    path = defn('engine = ">=99.0"')
    before = path.read_text(encoding="utf-8")
    argv = [cmd, str(path)]
    if cmd == "start":
        argv += ["--state-dir", str(tmp_path / "runs")]
    assert flow.main(argv) == 1
    err = capsys.readouterr().err
    assert "needs deskil 99.0 or newer (installed: 1.0.0)" in err
    assert "run `uv tool upgrade deskil`" in err
    assert path.read_text(encoding="utf-8") == before


def test_engine_too_new_in_json_lint(flow, defn, capsys):
    path = defn('engine = ">=99.0"')
    flow.main(["lint", str(path), "--format", "json"])
    issues = json.loads(capsys.readouterr().out)["issues"]
    assert any(
        "uv tool upgrade deskil" in i["message"] and i["code"] == "read-error"
        for i in issues
    )


@pytest.mark.parametrize(
    "value", ['">1.4"', '"1.4"', '"<=2"', '">=1.x"', '">=1."', "3"]
)
def test_engine_bad_format_is_a_lint_error(flow, defn, capsys, value):
    path = defn(f"engine = {value}")
    issues = flow.lint(path)
    assert any(i.level == "error" and i.where == "engine" for i in issues)
    # a bad value is reported, never a crash or a traceback
    assert flow.main(["dry-run", str(path)]) == 1
    assert "Traceback" not in capsys.readouterr().err


def test_engine_in_a_part_is_an_error(flow, write_def, tmp_path):
    (tmp_path / "part.toml").write_text(
        'schema = 1\nengine = ">=1.0"\nstart = "a"\n\n'
        '[states.a]\nprompt = "x"\nend = true\n',
        encoding="utf-8",
    )
    root = write_def(
        tmp_path,
        'schema = 1\nstart = "p"\n\n[states.p]\ninclude = "part.toml"\n'
        'exits = { a = "done" }\n\n[states.done]\nprompt = "x"\nend = true\n',
    )
    issues = flow.lint(root)
    assert any(
        i.level == "error"
        and "engine is only allowed in the root definition" in i.message
        for i in issues
    )


def test_new_template_mentions_engine_and_stays_valid(flow, tmp_path, capsys):
    assert '# engine = ">=1.0"' in flow.NEW_TEMPLATE
    path = tmp_path / "n.toml"
    assert flow.main(["new", str(path)]) == 0
    assert flow.lint(path) == []
    assert flow.main(["fmt", str(path), "--check"]) == 0


def test_schema_file_knows_engine(flow):
    schema = json.loads(Path(flow.SCHEMA_FILE).read_text(encoding="utf-8"))
    assert schema["properties"]["engine"]["type"] == "string"
