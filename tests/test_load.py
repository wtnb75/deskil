import pytest

FULL = """\
schema = 1
start = "s1_1"

[notes]
always = ["no xyz", { file = "notes/global.md" }]

[notes.common]
abc = "watch abc"
def = { file = "notes/def.md" }

[states.s1_1]
prompt = { file = "prompts/s1_1.md" }
notes = ["abc"]

[[states.s1_1.choices]]
label = "xxx"
when = "build ok"
goto = "s2"

[[states.s1_1.choices]]
label = "other"
when = "anything else"
goto = "s1_2"

[states.s1_2]
prompt = "Do B"
goto = "s2"

[states.s2]
prompt = "Do C"
goto = "s3"

[states.s3]
prompt = "Do D"
goto = "s2"
max_visits = 2
on_exceed = "s4"

[states.s4]
prompt = "Report"
end = true
"""


@pytest.fixture
def full_def(write_def, tmp_path):
    for rel in ("prompts/s1_1.md", "notes/global.md", "notes/def.md"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"body of {rel}\n", encoding="utf-8")
    return write_def(tmp_path, FULL)


def test_load_builds_definition(flow, full_def, tmp_path):
    d = flow.load_definition(full_def)
    assert d.start == "s1_1"
    assert d.path == full_def.resolve()
    assert d.base_dir == tmp_path.resolve()
    assert len(d.always) == 2 and d.always[0] == "no xyz"
    assert set(d.common) == {"abc", "def"}
    s1 = d.states["s1_1"]
    assert [c.label for c in s1.choices] == ["xxx", "other"]
    assert s1.choices[0].goto == "s2" and s1.choices[0].when == "build ok"
    assert s1.notes == ("abc",) and s1.goto is None and not s1.end
    s3 = d.states["s3"]
    assert (s3.goto, s3.max_visits, s3.on_exceed) == ("s2", 2, "s4")
    assert d.states["s4"].end is True


def test_load_rejects_lint_errors(flow, write_def, tmp_path):
    p = write_def(tmp_path, FULL.replace("[states.s4]", "[states.s4]\nbogus = 1"))
    with pytest.raises(flow.FlowError) as exc:
        flow.load_definition(p)
    assert "unknown-key" in str(exc.value)


def test_read_text_value_inline(flow, tmp_path):
    assert flow.read_text_value("hello", tmp_path) == "hello"


def test_read_text_value_file_strips_one_trailing_newline(flow, tmp_path):
    (tmp_path / "t.md").write_text("line1\nline2\n\n", encoding="utf-8")
    assert flow.read_text_value({"file": "t.md"}, tmp_path) == "line1\nline2\n"


def test_read_text_value_missing_file_raises(flow, tmp_path):
    with pytest.raises(flow.FlowError):
        flow.read_text_value({"file": "nope.md"}, tmp_path)


def test_read_text_value_not_utf8_raises(flow, tmp_path):
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(flow.FlowError):
        flow.read_text_value({"file": "bad.md"}, tmp_path)


def test_format_issue(flow):
    issue = flow.Issue("error", "orphan", "states.x", "not reachable")
    assert flow.format_issue(issue) == "error[orphan] states.x: not reachable"


def test_load_reads_the_toml_once(flow, full_def, monkeypatch):
    calls = []
    real = flow.read_toml
    monkeypatch.setattr(flow, "read_toml", lambda p: calls.append(p) or real(p))
    flow.load_definition(full_def)
    assert len(calls) == 1
