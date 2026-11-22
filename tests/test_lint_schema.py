import tomllib

import pytest

TOP = 'schema = 1\nstart = "a"\n'
A = 'prompt = "A"\ngoto = "b"\n'
B = 'prompt = "B"\nend = true\n'


def make(top=TOP, a=A, b=B, extra=""):
    """Build a two-state definition; override pieces to inject a defect."""
    return f"{top}\n{extra}\n[states.a]\n{a}\n[states.b]\n{b}\n"


def choice(label="x", when='when = "w"\n', goto="b"):
    return f'[[states.a.choices]]\nlabel = "{label}"\n{when}goto = "{goto}"\n'


def run(flow, text, base):
    return flow.lint_schema(tomllib.loads(text), base)


def test_valid_definition_has_no_issues(flow, tmp_path):
    assert run(flow, make(), tmp_path) == []


def test_valid_definition_with_choices_notes_and_files(flow, tmp_path):
    (tmp_path / "a.md").write_text("A body\n", encoding="utf-8")
    text = make(
        top='schema = 1\nstart = "a"\n[notes]\nalways = ["be careful"]\n',
        a='prompt = { file = "a.md" }\nnotes = ["n1"]\n'
        + choice("x")
        + choice("y"),
        extra='[notes.common]\nn1 = "note one"\n',
    )
    assert run(flow, text, tmp_path) == []


CASES = [
    ("no-schema", make(top='start = "a"\n'), "schema"),
    ("bad-schema", make(top='schema = 2\nstart = "a"\n'), "schema"),
    ("no-start", make(top="schema = 1\n"), "start"),
    ("start-not-a-state", make(top='schema = 1\nstart = "zzz"\n'), "start"),
    ("unknown-top-key", make(top=TOP + "foo = 1\n"), "unknown-key"),
    ("unknown-state-key", make(a=A + "bogus = 1\n"), "unknown-key"),
    ("unknown-choice-key", make(a=A.replace('goto = "b"\n', "") + choice() + "z = 1\n"), "unknown-key"),
    ("delegate-not-a-string", make(a=A + "delegate = 1\n"), "type"),
    ("delegate-bad-name", make(a=A + 'delegate = "my agent"\n'), "type"),
    ("delegate-on-end", make(b=B + 'delegate = "x"\n'), "end-with-transition"),
    ("notes-not-table", make(top=TOP + "notes = 1\n"), "type"),
    ("state-notes-not-list", make(a=A + 'notes = "x"\n'), "type"),
    ("max-visits-zero", make(a=A + 'max_visits = 0\non_exceed = "b"\n'), "type"),
    (
        "id-format",
        'schema = 1\nstart = "1a"\n[states."1a"]\nprompt = "A"\nend = true\n',
        "id-format",
    ),
    ("label-format", make(a='prompt = "A"\n' + choice("bad-label")), "label-format"),
    ("missing-target-goto", make(a='prompt = "A"\ngoto = "zzz"\n'), "missing-target"),
    (
        "missing-target-on-exceed",
        make(a=A + 'max_visits = 2\non_exceed = "zzz"\n'),
        "missing-target",
    ),
    ("missing-target-choice", make(a='prompt = "A"\n' + choice(goto="zzz")), "missing-target"),
    ("transition-none", make(a='prompt = "A"\n'), "transition-count"),
    ("transition-both", make(a=A + choice()), "transition-count"),
    ("end-with-goto", make(b=B + 'goto = "a"\n'), "end-with-transition"),
    (
        "label-duplicate",
        make(a='prompt = "A"\n' + choice("x") + choice("x")),
        "label-duplicate",
    ),
    ("when-missing", make(a='prompt = "A"\n' + choice(when="")), "when-missing"),
    ("on-exceed-missing", make(a=A + "max_visits = 2\n"), "on-exceed-missing"),
    (
        "on-exceed-without-max-visits",
        make(a=A + 'on_exceed = "b"\n'),
        "on-exceed-without-max-visits",
    ),
    ("end-with-on-exceed", make(b=B + 'on_exceed = "a"\n'), "end-with-transition"),
    ("goto-not-a-string", make(a='prompt = "A"\ngoto = ["b"]\n'), "type"),
    (
        "on-exceed-not-a-string",
        make(a=A + "max_visits = 2\non_exceed = { x = 1 }\n"),
        "type",
    ),
    (
        "choice-goto-not-a-string",
        make(a='prompt = "A"\n[[states.a.choices]]\nlabel = "x"\nwhen = "w"\ngoto = ["b"]\n'),
        "type",
    ),
    ("prompt-missing", make(a='goto = "b"\n'), "prompt-missing"),
    (
        "file-missing",
        make(a='prompt = { file = "nope.md" }\ngoto = "b"\n'),
        "file-missing",
    ),
    ("note-undefined", make(a=A + 'notes = ["zzz"]\n'), "note-undefined"),
]


@pytest.mark.parametrize("text,code", [(t, c) for _, t, c in CASES], ids=[n for n, _, _ in CASES])
def test_schema_errors(flow, tmp_path, text, code):
    issues = run(flow, text, tmp_path)
    assert code in {i.code for i in issues}
    assert all(i.level == "error" for i in issues)


@pytest.mark.parametrize("name", ["reviewer", "code-reviewer", "plugin:agent", "a_b.c"])
def test_delegate_is_accepted(flow, tmp_path, name):
    assert run(flow, make(a=A + f'delegate = "{name}"\n'), tmp_path) == []


@pytest.mark.parametrize("path", ["../x.md", "/etc/passwd"])
def test_file_outside(flow, tmp_path, path):
    text = make(a=f'prompt = {{ file = "{path}" }}\ngoto = "b"\n')
    assert "file-outside" in {i.code for i in run(flow, text, tmp_path)}


def test_issue_where_points_at_state(flow, tmp_path):
    issues = run(flow, make(a='goto = "b"\n'), tmp_path)
    missing = [i for i in issues if i.code == "prompt-missing"]
    assert missing and "states.a" in missing[0].where


def test_non_table_input_does_not_raise(flow, tmp_path):
    issues = flow.lint_schema({"schema": 1, "start": "a", "states": 3}, tmp_path)
    assert "type" in {i.code for i in issues}
