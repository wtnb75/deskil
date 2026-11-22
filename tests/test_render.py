import pytest

WITH_NOTES = """\
schema = 1
start = "s1"

[notes]
always = ["Do not do xyz"]

[notes.common]
abc = "Watch out for abc"
other = { file = "notes/other.md" }

[states.s1]
prompt = "Do task A"
notes = ["abc"]

[[states.s1.choices]]
label = "xxx"
when = "Build succeeded"
goto = "s2"

[[states.s1.choices]]
label = "other"
when = "Anything else"
goto = "s2"

[states.s2]
prompt = { file = "prompts/s2.md" }
goto = "s3"

[states.s3]
prompt = "All done"
end = true
"""

PLAIN = """\
schema = 1
start = "a"

[states.a]
prompt = "Do A"
goto = "b"

[states.b]
prompt = "Finish"
end = true
"""


@pytest.fixture
def notes_def(flow, write_def, tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "s2.md").write_text("Prompt for s2\n", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "other.md").write_text("never read here\n", encoding="utf-8")
    return write_def(tmp_path, WITH_NOTES)


def render(flow, path, state, run="R1"):
    return flow.render_step(flow.load_definition(path), state, run, cmd="flow")


def test_render_choices(flow, notes_def):
    assert render(flow, notes_def, "s1") == (
        "[s1] (run: R1)\n"
        "Do task A\n"
        "\n"
        "Notes:\n"
        "- Do not do xyz\n"
        "- Watch out for abc\n"
        "\n"
        "After finishing the work, report the result with one of the following:\n"
        "  flow next R1 --result xxx   : Build succeeded\n"
        "  flow next R1 --result other : Anything else\n"
    )


def test_render_delegate(flow, write_def, tmp_path):
    p = write_def(tmp_path, PLAIN.replace('prompt = "Do A"\n', 'prompt = "Do A"\ndelegate = "reviewer"\n'))
    assert render(flow, p, "a") == (
        "[a] (run: R1)\n"
        "Do A\n"
        "\n"
        "Delegate: hand this step to the subagent `reviewer` (Agent tool, subagent_type = reviewer). "
        "Give it this whole step text. It does the work, runs the command shown below, "
        "and returns that command's output to you. Continue from that output.\n"
        "\n"
        "After finishing the work, run:\n"
        "  flow next R1\n"
    )


def test_render_without_delegate_has_no_delegate_section(flow, write_def, tmp_path):
    p = write_def(tmp_path, PLAIN)
    assert "Delegate" not in render(flow, p, "a")


def test_render_no_choices_goto(flow, write_def, tmp_path):
    p = write_def(tmp_path, PLAIN)
    assert render(flow, p, "a") == (
        "[a] (run: R1)\nDo A\n\nAfter finishing the work, run:\n  flow next R1\n"
    )


def test_render_end(flow, write_def, tmp_path):
    p = write_def(tmp_path, PLAIN)
    assert render(flow, p, "b") == "[b] (run: R1)\nFinish\n\nFlow complete.\n"


def test_render_always_and_notes_deduplicated(flow, write_def, tmp_path):
    text = PLAIN.replace(
        "[states.a]",
        '[notes]\nalways = ["same", "same"]\n[notes.common]\nn1 = "same"\nn2 = "different"\n\n[states.a]',
    ).replace('goto = "b"', 'goto = "b"\nnotes = ["n1", "n2"]')
    out = render(flow, write_def(tmp_path, text), "a")
    assert out.count("- same\n") == 1
    assert "- different\n" in out


def test_render_without_notes_has_no_notes_section(flow, write_def, tmp_path):
    out = render(flow, write_def(tmp_path, PLAIN), "a")
    assert "Notes:" not in out


def test_render_reads_files_only_for_current_state(flow, notes_def, tmp_path):
    defn = flow.load_definition(notes_def)
    (tmp_path / "prompts" / "s2.md").unlink()  # s2's prompt
    (tmp_path / "notes" / "other.md").unlink()  # unreferenced common note
    out = flow.render_step(defn, "s1", "R1", cmd="flow")
    assert "Do task A" in out


def test_render_missing_prompt_file_raises_flowerror(flow, notes_def, tmp_path):
    defn = flow.load_definition(notes_def)
    (tmp_path / "prompts" / "s2.md").unlink()
    with pytest.raises(flow.FlowError):
        flow.render_step(defn, "s2", "R1", cmd="flow")
