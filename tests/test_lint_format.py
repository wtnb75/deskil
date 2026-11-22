import json

import pytest

OK = """\
schema = 1
start = "a"

[states.a]
prompt = "A"
end = true
"""

BAD = OK.replace("[states.a]", "[states.a]\nbogus = 1")

WARN = """\
schema = 1
start = "a"

[states.a]
prompt = "A"

[[states.a.choices]]
label = "x"
when = "w"
goto = "b"

[states.b]
prompt = "B"
end = true
"""


def lint(flow, write_def, tmp_path, text, fmt, capsys, name="f.toml"):
    path = write_def(tmp_path, text, name)
    code = flow.main(["lint", str(path), "--format", fmt])
    return path, code, capsys.readouterr()


def test_default_format_is_text(flow, write_def, tmp_path, capsys):
    path = write_def(tmp_path, BAD)
    assert flow.main(["lint", str(path)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("error[unknown-key] ")


def test_text_format_is_explicit_text(flow, write_def, tmp_path, capsys):
    _, code, cap = lint(flow, write_def, tmp_path, BAD, "text", capsys)
    assert code == 1 and cap.out.startswith("error[unknown-key] ")


def test_json_lists_issues(flow, write_def, tmp_path, capsys):
    path, code, cap = lint(flow, write_def, tmp_path, BAD, "json", capsys)
    data = json.loads(cap.out)
    assert code == 1
    assert data["file"] == str(path)
    assert data["issues"] == [
        {
            "level": "error",
            "code": "unknown-key",
            "where": "states.a",
            "message": "unknown key 'bogus'",
        }
    ]


def test_json_clean_definition(flow, write_def, tmp_path, capsys):
    path, code, cap = lint(flow, write_def, tmp_path, OK, "json", capsys)
    assert code == 0
    assert json.loads(cap.out) == {"file": str(path), "issues": []}


def test_json_warning_only_exits_0(flow, write_def, tmp_path, capsys):
    _, code, cap = lint(flow, write_def, tmp_path, WARN, "json", capsys)
    assert code == 0
    assert [i["level"] for i in json.loads(cap.out)["issues"]] == ["warning"]


def test_github_error_and_warning_commands(flow, write_def, tmp_path, capsys):
    path, code, cap = lint(flow, write_def, tmp_path, BAD, "github", capsys)
    assert code == 1
    assert (
        cap.out == f"::error file={path}::[unknown-key] states.a: unknown key 'bogus'\n"
    )
    path, code, cap = lint(flow, write_def, tmp_path, WARN, "github", capsys, "w.toml")
    assert code == 0
    assert cap.out.startswith(f"::warning file={path}::[single-choice] states.a: ")


def test_github_escapes_properties_and_data(flow):
    assert flow._gh_property("a:b,c%d\ne") == "a%3Ab%2Cc%25d%0Ae"
    assert flow._gh_data("x%y\r\nz") == "x%25y%0D%0Az"


@pytest.mark.parametrize("fmt", ["json", "github"])
def test_unreadable_toml_is_reported_in_the_format(
    flow, write_def, tmp_path, capsys, fmt
):
    path, code, cap = lint(flow, write_def, tmp_path, "not = [valid", fmt, capsys)
    assert code == 1 and cap.err == ""
    if fmt == "json":
        issue = json.loads(cap.out)["issues"][0]
        assert issue["level"] == "error" and issue["code"] == "read-error"
    else:
        assert cap.out.startswith("::error file=") and "[read-error]" in cap.out


def test_unreadable_toml_in_text_format_is_still_a_plain_error(
    flow, write_def, tmp_path, capsys
):
    _, code, cap = lint(flow, write_def, tmp_path, "not = [valid", "text", capsys)
    assert code == 1 and cap.out == "" and cap.err.startswith("error: ")


def test_unknown_format_is_a_usage_error(flow, write_def, tmp_path):
    path = write_def(tmp_path, OK)
    with pytest.raises(SystemExit) as exc:
        flow.main(["lint", str(path), "--format", "xml"])
    assert exc.value.code == 2
