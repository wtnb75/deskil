import tomllib

import pytest

MESSY = """\
# A flow that needs tidying
start = "a"   # first state
schema = 1
[states.a]
goto = "b"
prompt = '''
goto = "zzz"
[states.fake] stays
'''
# keep with prompt of b
[states.b]
end = true
on_exceed = "a"
prompt="Done"
  [[states.b.choices]]
goto = "a"
when = "w"
label = "x"
"""


def test_new_matches_fmt_and_lints(flow, tmp_path):
    p = tmp_path / "flow.toml"
    flow.new_definition(p)
    assert flow.lint(p) == []
    assert flow.format_text(p.read_text(encoding="utf-8")) == flow.NEW_TEMPLATE
    assert flow.format_definition(p) is False


def test_new_refuses_existing_file(flow, tmp_path):
    p = tmp_path / "flow.toml"
    p.write_text("keep", encoding="utf-8")
    with pytest.raises(flow.FlowError):
        flow.new_definition(p)
    assert p.read_text(encoding="utf-8") == "keep"


def test_fmt_sorts_keys_and_keeps_comments(flow):
    text = (
        "# top comment\n"
        'start = "a"   # first state\n'
        "schema = 1\n"
        "[states.a]\n"
        'goto = "a"\n'
        "# about prompt\n"
        'prompt="P"\n'
        "max_visits = 1\n"
        'on_exceed = "a"\n'
    )
    out = flow.format_text(text)
    assert out == (
        "schema = 1\n"
        "# top comment\n"
        'start = "a"   # first state\n'
        "\n"
        "[states.a]\n"
        "# about prompt\n"
        'prompt = "P"\n'
        'goto = "a"\n'
        "max_visits = 1\n"
        'on_exceed = "a"\n'
    )


def test_fmt_leaves_multiline_strings_alone(flow):
    text = 'schema = 1\nstart = "a"\n\n[states.a]\nend = true\nprompt = """\nend = true\n  [states.x]   \n"""\n'
    out = flow.format_text(text)
    assert 'prompt = """\nend = true\n  [states.x]   \n"""\nend = true\n' in out
    assert tomllib.loads(out) == tomllib.loads(text)


def test_fmt_handles_multiline_arrays(flow):
    text = (
        'schema = 1\nstart = "a"\n\n[notes]\ncommon = { a = "x" }\n'
        'always = [\n  "one",  # c\n  "two",\n]\n\n'
        '[states.a]\nend = true\nprompt = "p"\n'
    )
    out = flow.format_text(text)
    assert out.index("always = [") < out.index("common = ")
    assert '  "one",  # c\n  "two",\n]\n' in out
    assert tomllib.loads(out) == tomllib.loads(text)


def test_fmt_is_idempotent_and_preserves_data(flow, tmp_path, write_def):
    p = write_def(tmp_path, MESSY)
    before = tomllib.loads(MESSY)
    assert flow.format_definition(p) is True
    once = p.read_text(encoding="utf-8")
    assert tomllib.loads(once) == before
    assert (
        "# A flow that needs tidying\nschema = 1" not in once
    )  # comment moved with `start`
    assert "# keep with prompt of b\n[states.b]" in once
    assert flow.format_definition(p) is False
    assert p.read_text(encoding="utf-8") == once


def test_fmt_keeps_mode_and_symlink(flow, tmp_path, write_def):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = write_def(real_dir, MESSY)
    real.chmod(0o640)
    link = tmp_path / "link.toml"
    link.symlink_to(real)
    assert flow.format_definition(link) is True
    assert link.is_symlink()
    assert (real.stat().st_mode & 0o7777) == 0o640
    assert tomllib.loads(real.read_text(encoding="utf-8")) == tomllib.loads(MESSY)
    assert sorted(x.name for x in real_dir.iterdir()) == [real.name]


def test_fmt_check_does_not_write(flow, tmp_path, write_def):
    p = write_def(tmp_path, MESSY)
    assert flow.format_definition(p, check=True) is True
    assert p.read_text(encoding="utf-8") == MESSY


def test_fmt_rejects_unsupported_keys(flow, tmp_path, write_def):
    text = 'schema = 1\nstart = "a"\n"quoted" = 1\n'
    p = write_def(tmp_path, text)
    with pytest.raises(flow.FlowError):
        flow.format_definition(p)
    assert p.read_text(encoding="utf-8") == text


def test_fmt_rejects_invalid_toml(flow, tmp_path, write_def):
    p = write_def(tmp_path, "schema = \n")
    with pytest.raises(flow.FlowError):
        flow.format_definition(p)


def test_cli_new_and_fmt(flow, tmp_path, capsys):
    p = tmp_path / "x.toml"
    assert flow.main(["new", str(p)]) == 0
    assert flow.main(["new", str(p)]) == 1
    assert flow.main(["fmt", "--check", str(p)]) == 0
    p.write_text(MESSY, encoding="utf-8")
    assert flow.main(["fmt", "--check", str(p)]) == 1
    assert p.read_text(encoding="utf-8") == MESSY
    assert flow.main(["fmt", str(p)]) == 0
    assert flow.main(["fmt", "--check", str(p)]) == 0
    out = capsys.readouterr().out
    assert "would reformat" in out and "formatted" in out


@pytest.mark.parametrize(
    "rel",
    [
        "plugins/deskil-dev/skills/impl/flow.toml",
        "plugins/deskil-dev/skills/add/flow.toml",
        "plugins/deskil-dev/skills/decide/flow.toml",
        "plugins/deskil-dev/skills/prio/flow.toml",
        "plugins/feature-a/skills/review-loop/flow.toml",
    ],
)
def test_fmt_keeps_data_of_real_definitions(flow, rel):
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / rel
    text = path.read_text(encoding="utf-8")
    out = flow.format_text(text)
    assert tomllib.loads(out) == tomllib.loads(text)
    assert flow.format_text(out) == out


def test_fmt_keeps_trailing_comment_with_its_table(flow):
    text = (
        'schema = 1\nstart = "a"\n\n[states.a]\nend = true\nprompt = "x"\n'
        '# trailing a\n\n# about b\n[states.b]\nend = true\nprompt = "y"\n'
    )
    out = flow.format_text(text)
    assert "end = true\n# trailing a\n\n# about b\n[states.b]" in out
    assert flow.format_text(out) == out


def test_fmt_order_covers_schema_keys(flow):
    assert set(flow.FMT_ORDER["state"]) | {"choices"} == flow.STATE_KEYS
    assert set(flow.FMT_ORDER["choice"]) == flow.CHOICE_KEYS
    assert set(flow.FMT_ORDER["arg"]) == flow.ARG_KEYS
    assert set(flow.FMT_ORDER["notes"]) == flow.NOTES_KEYS
    assert set(flow.FMT_ORDER["top"]) | {"notes", "args", "states"} == flow.TOP_KEYS


def test_new_does_not_write_through_a_dangling_symlink(flow, tmp_path):
    target = tmp_path / "target.toml"
    link = tmp_path / "link.toml"
    link.symlink_to(target)
    with pytest.raises(flow.FlowError):
        flow.new_definition(link)
    assert not target.exists()
