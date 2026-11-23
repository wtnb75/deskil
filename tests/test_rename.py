import pytest

DEF = """\
schema = 1
start = "s1"   # start here

[states.s1]
prompt = '''
Note: goto = "s2" is documented here
[states.s2] stays
'''

[[states.s1.choices]]
label = "go"
when = "w"
goto = "s2"

[[states.s1.choices]]
label = "skip"
when = "w2"
goto = "s3"

[states.s2]
prompt = "Loop"
goto = "s1"
max_visits = 2
on_exceed = "s3"

# [states.s3] is the final state
[states.s3]
prompt = "Done"
end = true
"""


@pytest.fixture
def p(write_def, tmp_path):
    return write_def(tmp_path, DEF)


def test_rename_updates_all_references(flow, p):
    flow.rename_state(p, "s2", "step_two")
    text = p.read_text(encoding="utf-8")
    assert "[states.step_two]" in text
    assert 'goto = "step_two"' in text
    assert "[states.s2]\nprompt" not in text
    assert flow.lint(p) == []


def test_rename_on_exceed_start_and_choice_headers(flow, p):
    flow.rename_state(p, "s3", "final", allow_end=True)
    flow.rename_state(p, "s1", "first")
    text = p.read_text(encoding="utf-8")
    assert 'on_exceed = "final"' in text
    assert 'start = "first"   # start here' in text
    assert "[[states.first.choices]]" in text and "[states.first]" in text
    assert 'goto = "first"' in text
    assert flow.lint(p) == []


def test_rename_leaves_prompt_text_and_comments_untouched(flow, p):
    flow.rename_state(p, "s2", "step_two")
    text = p.read_text(encoding="utf-8")
    assert 'Note: goto = "s2" is documented here' in text
    assert "[states.s2] stays" in text
    assert "# [states.s3] is the final state" in text


def test_rename_ignores_one_line_strings_and_trailing_comments(
    flow, write_def, tmp_path
):
    text = (
        'schema = 1\nstart = "a"\n'
        "[states.a]\nprompt = 'Set goto = \"b\" in the config'\n"
        'goto = "b"  # was goto = "b"\n'
        '[states.b]\nprompt = "B"\nend = true\n'
    )
    path = write_def(tmp_path, text)
    flow.rename_state(path, "b", "bee", allow_end=True)
    out = path.read_text(encoding="utf-8")
    assert "prompt = 'Set goto = \"b\" in the config'" in out
    assert 'goto = "bee"  # was goto = "b"' in out
    assert flow.lint(path) == []


def test_rename_handles_inline_tables(flow, write_def, tmp_path):
    text = (
        'schema = 1\nstart = "a"\n'
        '[states.a]\nprompt = "A"\n'
        'choices = [{ label = "x", when = "w", goto = "b" }, { label = "y", when = "v", goto = "c" }]\n'
        '[states.b]\nprompt = "B"\nend = true\n'
        '[states.c]\nprompt = "C"\nend = true\n'
    )
    path = write_def(tmp_path, text)
    flow.rename_state(path, "b", "bee", allow_end=True)
    assert 'goto = "bee" }' in path.read_text(encoding="utf-8")
    assert flow.lint(path) == []


def test_rename_does_not_touch_ids_with_the_same_prefix(flow, write_def, tmp_path):
    text = 'schema = 1\nstart = "a"\n[states.a]\nprompt = "A"\ngoto = "a2"\n[states.a2]\nprompt = "B"\nend = true\n'
    path = write_def(tmp_path, text)
    flow.rename_state(path, "a", "first")
    out = path.read_text(encoding="utf-8")
    assert 'start = "first"' in out and 'goto = "a2"' in out and "[states.a2]" in out


@pytest.mark.parametrize(
    "old,new",
    [("nope", "x"), ("s2", "1x"), ("s2", "a-b"), ("s2", "s3")],
    ids=["unknown-old", "bad-id-digit", "bad-id-dash", "existing-new"],
)
def test_rename_rejects_and_leaves_file_unchanged(flow, p, old, new):
    before = p.read_bytes()
    with pytest.raises(flow.FlowError):
        flow.rename_state(p, old, new)
    assert p.read_bytes() == before


def test_rename_rolls_back_when_lint_regresses(flow, write_def, tmp_path):
    # A reference written with a quoted key is not found by the text rewrite,
    # so the rename would leave a dangling goto. The lint check must catch it.
    text = (
        'schema = 1\nstart = "a"\n'
        '[states.a]\nprompt = "A"\n"goto" = "b"\n'
        '[states.b]\nprompt = "B"\nend = true\n'
    )
    path = write_def(tmp_path, text)
    before = path.read_bytes()
    with pytest.raises(flow.FlowError) as exc:
        flow.rename_state(path, "b", "c", allow_end=True)
    assert "missing-target" in str(exc.value)
    assert path.read_bytes() == before
    assert sorted(f.name for f in tmp_path.iterdir()) == ["flow.toml"]


def test_rename_refuses_an_end_state_unless_allowed(flow, write_def, tmp_path, capsys):
    path = write_def(tmp_path, PART)
    before = path.read_bytes()
    with pytest.raises(flow.FlowError) as exc:
        flow.rename_state(path, "ok", "done")
    assert "exits" in str(exc.value) and "--allow-end" in str(exc.value)
    # an invalid new id is reported before the end-state hint
    with pytest.raises(flow.FlowError, match="invalid state id"):
        flow.rename_state(path, "ok", "bad id")
    assert path.read_bytes() == before
    assert flow.main(["rename", str(path), "ok", "done"]) == 1
    assert "--allow-end" in capsys.readouterr().err
    assert path.read_bytes() == before
    assert flow.main(["rename", str(path), "ok", "done", "--allow-end"]) == 0
    assert "[states.done]" in path.read_text(encoding="utf-8")


def test_cli_rename(flow, p, capsys):
    assert flow.main(["rename", str(p), "s2", "step_two"]) == 0
    assert "step_two" in capsys.readouterr().out
    assert "[states.step_two]" in p.read_text(encoding="utf-8")
    assert flow.main(["rename", str(p), "nope", "x"]) == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("header", ["[states . s2]", '[states."s2"]', "[ states.s2 ]"])
def test_rename_handles_spaced_and_quoted_headers(flow, write_def, tmp_path, header):
    text = DEF.replace('[states.s2]\nprompt = "Loop"', f'{header}\nprompt = "Loop"')
    path = write_def(tmp_path, text)
    flow.rename_state(path, "s2", "step_two")
    out = path.read_text(encoding="utf-8")
    assert (
        'goto = "step_two"' in out
        and "step_two" in out.split('prompt = "Loop"')[0].splitlines()[-1]
    )
    assert flow.lint(path) == []


def test_rename_explains_when_the_header_cannot_be_found(flow, write_def, tmp_path):
    text = (
        'schema = 1\nstart = "a"\n[states]\n'
        'a.prompt = "A"\na.goto = "b"\nb.prompt = "B"\nb.end = true\n'
    )
    path = write_def(tmp_path, text)
    before = path.read_bytes()
    with pytest.raises(flow.FlowError) as exc:
        flow.rename_state(path, "b", "c", allow_end=True)
    assert "table header" in str(exc.value)
    assert path.read_bytes() == before


PART = (
    'schema = 1\nstart = "p"\n'
    '[states.p]\nprompt = "P"\nchoices = [\n'
    '  { label = "ok", when = "w", goto = "ok" },\n'
    '  { label = "bad", when = "w2", goto = "fail" },\n]\n'
    '[states.ok]\nprompt = "ok"\nend = true\n'
    '[states.fail]\nprompt = "fail"\nend = true\n'
)

INCLUDE_FORMS = {
    "inline": 'include = "part.toml"\nexits = { ok = "c", fail = "c" }  # c twice\n',
    "table": 'include = "part.toml"\n\n[states.i.exits]\nok = "c"\nfail = "c"\n',
    "dotted": 'include = "part.toml"\nexits.ok = "c"\nexits.fail = "c"\n',
}


@pytest.mark.parametrize("form", sorted(INCLUDE_FORMS))
def test_rename_updates_exits_values(flow, write_def, tmp_path, form):
    write_def(tmp_path, PART, name="part.toml")
    text = (
        'schema = 1\nstart = "i"\n[states.i]\n'
        + INCLUDE_FORMS[form]
        + '\n[states.c]\nprompt = "C"\nend = true\n'
    )
    path = write_def(tmp_path, text)
    assert flow.lint(path) == []
    flow.rename_state(path, "c", "done", allow_end=True)
    out = path.read_text(encoding="utf-8")
    assert out.count('"done"') == 2 and '"c"' not in out
    assert "[states.done]" in out
    assert flow.lint(path) == []


def test_rename_exits_leaves_other_values_and_keys(flow, write_def, tmp_path):
    write_def(tmp_path, PART, name="part.toml")
    text = (
        'schema = 1\nstart = "i"\n[states.i]\n'
        'include = "part.toml"\nexits = { ok = "c", fail = "d" }\n'
        '[states.c]\nprompt = "C"\nend = true\n'
        '[states.d]\nprompt = "D"\nend = true\n'
    )
    path = write_def(tmp_path, text)
    flow.rename_state(path, "c", "ok", allow_end=True)  # new id equals an exits key
    assert 'exits = { ok = "ok", fail = "d" }' in path.read_text(encoding="utf-8")
    assert flow.lint(path) == []


def test_rename_of_an_include_state_keeps_its_exits(flow, write_def, tmp_path):
    write_def(tmp_path, PART, name="part.toml")
    text = (
        'schema = 1\nstart = "i"\n[states.i]\n'
        'include = "part.toml"\nexits = { ok = "i2", fail = "i2" }\n'
        '[states.i2]\ninclude = "part.toml"\nexits = { ok = "e", fail = "e" }\n'
        '[states.e]\nprompt = "E"\nend = true\n'
    )
    path = write_def(tmp_path, text)
    flow.rename_state(path, "i2", "next")
    out = path.read_text(encoding="utf-8")
    assert 'exits = { ok = "next", fail = "next" }' in out
    assert "[states.next]" in out
    assert flow.lint(path) == []
