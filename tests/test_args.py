import json
import re

import pytest

DEF = """\
schema = 1
start = "a"

[args.item]
required = true

[args.mode]
default = "fast"

[notes]
always = ["Item {{arg.item}}"]

[states.a]
prompt = "Work on {{arg.item}} in {{arg.mode}} mode"

[[states.a.choices]]
label = "go"
when = "done with {{arg.item}}"
goto = "e"

[states.e]
prompt = "Done"
end = true
"""


@pytest.fixture
def path(write_def, tmp_path):
    return write_def(tmp_path, DEF)


def rid_of(out):
    return re.search(r"\(run: ([^)]+)\)", out).group(1)


def test_start_substitutes_and_records(flow, path, tmp_path):
    runs = tmp_path / "runs"
    out = flow.start_run(path, runs, args={"item": "B-1"})
    assert "Work on B-1 in fast mode" in out
    assert "- Item B-1" in out
    assert "done with B-1" in out
    data = json.loads((runs / f"{rid_of(out)}.json").read_text(encoding="utf-8"))
    assert data["args"] == {"item": "B-1", "mode": "fast"}


def test_next_keeps_substituting(flow, path, tmp_path):
    runs = tmp_path / "runs"
    out = flow.start_run(path, runs, args={"item": "B-1", "mode": "slow"})
    out = flow.next_step(rid_of(out), "go", runs)
    assert "Done" in out
    assert "Args: item=B-1, mode=slow" in flow.status_text(rid_of(out), runs)


def test_missing_required(flow, path, tmp_path):
    with pytest.raises(flow.FlowError, match="missing required argument: item"):
        flow.start_run(path, tmp_path / "runs")
    assert not list((tmp_path / "runs").glob("*.json"))


def test_unknown_argument(flow, path, tmp_path):
    with pytest.raises(flow.FlowError, match="unknown argument: x"):
        flow.start_run(path, tmp_path / "runs", args={"item": "1", "x": "2"})


def test_parse_arg_options(flow):
    assert flow.parse_args(["a=1", "b=x=y"]) == {"a": "1", "b": "x=y"}
    with pytest.raises(flow.FlowError, match="key=value"):
        flow.parse_args(["nokey"])
    with pytest.raises(flow.FlowError, match="given twice"):
        flow.parse_args(["a=1", "a=2"])


def test_lint_unknown_reference(flow, write_def, tmp_path):
    p = write_def(tmp_path, DEF.replace("{{arg.mode}}", "{{arg.nope}}"))
    codes = [i.code for i in flow.lint(p)]
    assert "unknown-arg" in codes


ROOT_WITH_PART = """\
schema = 1
start = "a"

[args.item]
required = true

[states.a]
prompt = "go"
goto = "p"

[states.p]
include = "part.toml"
exits = { ok = "e" }

[states.e]
prompt = "Done"
end = true
"""

PART_TEXT = """\
schema = 1
start = "r"

[states.r]
prompt = "{prompt}"
goto = "ok"

[states.ok]
prompt = "ok"
end = true
"""


def _part_def(write_def, tmp_path, prompt):
    write_def(tmp_path, PART_TEXT.replace("{prompt}", prompt), "part.toml")
    return write_def(tmp_path, ROOT_WITH_PART)


def test_lint_unknown_reference_in_part(flow, write_def, tmp_path):
    p = _part_def(write_def, tmp_path, "work on {{arg.nope}}")
    issues = [i for i in flow.lint(p) if i.code == "unknown-arg"]
    assert [i.where for i in issues] == ["states.p__r.prompt"]


def test_lint_declared_reference_in_part(flow, write_def, tmp_path):
    p = _part_def(write_def, tmp_path, "work on {{arg.item}}")
    assert not [i for i in flow.lint(p) if i.level == "error"]


def test_lint_unknown_reference_in_file_text(flow, write_def, tmp_path):
    (tmp_path / "text.md").write_text("see {{arg.nope}}\n", encoding="utf-8")
    p = write_def(
        tmp_path,
        'schema = 1\nstart = "a"\n[states.a]\nprompt = { file = "text.md" }\nend = true\n',
    )
    issues = [i for i in flow.lint(p) if i.code == "unknown-arg"]
    assert [i.where for i in issues] == ["states.a.prompt"]


def test_lint_unknown_reference_in_part_file_text(flow, write_def, tmp_path):
    (tmp_path / "text.md").write_text("see {{arg.nope}}\n", encoding="utf-8")
    p = _part_def(write_def, tmp_path, "x")
    (tmp_path / "part.toml").write_text(
        PART_TEXT.replace('"{prompt}"', '{ file = "text.md" }'), encoding="utf-8"
    )
    issues = [i for i in flow.lint(p) if i.code == "unknown-arg"]
    assert [i.where for i in issues] == ["states.p__r.prompt"]


@pytest.mark.parametrize(
    "block, code",
    [
        ('[args.x]\nrequired = true\ndefault = "a"\n', "arg-default-required"),
        ("[args.x]\nrequired = 1\n", "type"),
        ("[args.x]\ndefault = 1\n", "type"),
        ('[args.x]\ntype = "int"\n', "unknown-key"),
        ('[args."a-b"]\n', "arg-name"),
    ],
)
def test_lint_arg_declaration(flow, write_def, tmp_path, block, code):
    text = (
        'schema = 1\nstart = "a"\n\n'
        + block
        + '\n[states.a]\nprompt = "p"\nend = true\n'
    )
    p = write_def(tmp_path, text)
    assert code in [i.code for i in flow.lint(p)]


def test_args_in_part_rejected(flow, write_def, tmp_path):
    write_def(
        tmp_path,
        'schema = 1\nstart = "p"\n\n[args.x]\n\n[states.p]\nprompt = "p"\nend = true\n',
        "part.toml",
    )
    root = write_def(
        tmp_path,
        'schema = 1\nstart = "i"\n\n[states.i]\ninclude = "part.toml"\n'
        '[states.i.exits]\np = "e"\n\n[states.e]\nprompt = "e"\nend = true\n',
    )
    assert "include-args" in [i.code for i in flow.lint(root)]


def test_cli_arg_option(flow, path, tmp_path, capsys):
    runs = str(tmp_path / "runs")
    rc = flow.main(["start", str(path), "--state-dir", runs, "--arg", "item=Z"])
    assert rc == 0
    assert "Work on Z" in capsys.readouterr().out
    rc = flow.main(["start", str(path), "--state-dir", runs])
    assert rc == 1
    assert "missing required argument" in capsys.readouterr().err
