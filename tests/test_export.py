"""Tests for `flow export`: a definition written back as plain skill instructions."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLOW_PY = ROOT / "shared" / "flow" / "flow.py"
REAL_DEFS = sorted((ROOT / "plugins").glob("*/skills/*/flow.toml"))

DEF = """\
schema = 1
start = "a"

[notes]
always = ["Stay in the project."]

[states.a]
prompt = "Do A"
notes = ["tip"]

[[states.a.choices]]
label = "again"
when = "needs more work"
goto = "w"

[[states.a.choices]]
label = "stop"
when = "enough"
goto = "done"

[states.w]
prompt = "Work"
goto = "a"
max_visits = 3
on_exceed = "done"

[states.done]
prompt = "Done"
end = true

[notes.common]
tip = "Be brief."
"""

DEF_RUN = """\
schema = 1
start = "a"

[states.a]
run = ["echo", "hi there"]
delegate = "helper"
prompt = "Look at the output"
goto = "z"

[states.z]
prompt = "Done"
end = true
"""

DEF_JA = DEF_RUN.replace("Look at the output", "出力を確認して、結果をまとめる")


def parse_export(md: str) -> dict:
    """Read the symbols of an export: start, and per state its edges and limit."""
    start = re.match(r"[^`]*`(\w+)`", md).group(1)
    states: dict[str, dict] = {}
    cur = None
    for line in md.splitlines():
        m = re.fullmatch(r"## (\w+)", line)
        if m:
            cur = states.setdefault(
                m.group(1), {"choices": [], "goto": None, "end": False}
            )
            continue
        if cur is None:
            continue
        if m := re.fullmatch(r"- `(\w+)` → `(\w+)`: (.*)", line):
            cur["choices"].append((m.group(1), m.group(2), m.group(3)))
        elif m := re.fullmatch(r"→ `(\w+)`", line):
            cur["goto"] = m.group(1)
        elif m := re.fullmatch(
            r"\(.*?(\d+).*→ `(\w+)`\)|（.*?(\d+).*→ `(\w+)`）", line
        ):
            cur["limit"] = (int(m.group(1) or m.group(3)), m.group(2) or m.group(4))
        elif line.startswith("(") and line.endswith(")") or line.startswith("（"):
            cur["end"] = True
    return {"start": start, "states": states}


@pytest.fixture
def p(write_def, tmp_path):
    return write_def(tmp_path, DEF)


def test_each_state_is_a_section_in_definition_order(flow, p):
    md, _ = flow.export_skill(p, "en")
    assert re.findall(r"^## (\w+)$", md, re.MULTILINE) == ["a", "w", "done"]
    assert md.startswith("Start at `a`.")


def test_choices_gotos_and_limits_are_symbols(flow, p):
    md, _ = flow.export_skill(p, "en")
    assert "- `again` → `w`: needs more work" in md
    assert "- `stop` → `done`: enough" in md
    assert "→ `a`\n(at most 3 times → `done`)" in md


def test_notes_are_copied_and_always_notes_are_written_once(flow, p):
    md, _ = flow.export_skill(p, "en")
    assert md.count("Stay in the project.") == 1
    assert "Notes:\n- Be brief." in md


def test_the_japanese_wording(flow, p):
    md, _ = flow.export_skill(p, "ja")
    assert md.startswith("`a` から始める。")
    assert "（最大 3 回 → `done`）" in md
    assert "- `again` → `w`: needs more work" in md  # copied as is


def test_language_is_detected_from_kana_and_can_be_overridden(
    flow, write_def, tmp_path
):
    ja = write_def(tmp_path, DEF_JA)
    assert flow.export_skill(ja)[0].startswith("`a` から始める。")
    assert flow.export_skill(ja, "en")[0].startswith("Start at `a`.")
    en = write_def(tmp_path, DEF_RUN, "en.toml")
    assert flow.export_skill(en)[0].startswith("Start at `a`.")


def test_kanji_alone_does_not_make_it_japanese(flow):
    assert flow.detect_export_lang(["edit 背景 and 概要"]) == "en"


def test_unknown_language_is_an_error(flow, p):
    with pytest.raises(flow.FlowError):
        flow.export_skill(p, "fr")


def test_dropped_items_are_listed_and_noted_in_the_text(flow, p):
    md, dropped = flow.export_skill(p, "en")
    assert dropped == ["state w: max_visits 3 is no longer enforced (on_exceed: done)"]
    assert "Not enforced without the flow engine: max_visits." in md


def test_run_and_delegate_are_kept_in_the_text_and_reported(flow, write_def, tmp_path):
    md, dropped = flow.export_skill(write_def(tmp_path, DEF_RUN), "en")
    assert "Run `echo 'hi there'` first." in md
    assert "Hand this step to the subagent `helper`." in md
    assert "Not enforced without the flow engine: run, delegate." in md
    assert any("run is no longer executed" in d for d in dropped)
    assert any("delegate" in d for d in dropped)


def test_prompt_files_are_copied_in_and_reported(flow, write_def, tmp_path):
    (tmp_path / "p.md").write_text("From a file\n", encoding="utf-8")
    path = write_def(
        tmp_path,
        'schema = 1\nstart = "a"\n[states.a]\nprompt = { file = "p.md" }\nend = true\n',
    )
    md, dropped = flow.export_skill(path, "en")
    assert "From a file" in md
    assert dropped == ["state a: the prompt file p.md was copied in"]


def test_includes_are_merged_and_reported(flow, write_def, tmp_path):
    write_def(
        tmp_path,
        'schema = 1\nstart = "x"\n[states.x]\nprompt = "X"\ngoto = "y"\n[states.y]\nprompt = "Y"\nend = true\n',
        "part.toml",
    )
    path = write_def(
        tmp_path,
        'schema = 1\nstart = "a"\n[states.a]\ninclude = "part.toml"\nexits = { y = "b" }\n'
        '[states.b]\nprompt = "B"\nend = true\n',
    )
    md, dropped = flow.export_skill(path, "en")
    assert any(d.startswith("include:") for d in dropped)
    assert "## b" in md


def test_a_definition_with_errors_is_rejected(flow, write_def, tmp_path):
    path = write_def(tmp_path, DEF.replace("[states.done]", "[states.done]\nbogus = 1"))
    with pytest.raises(flow.FlowError):
        flow.export_skill(path)


def test_cli_prints_text_to_stdout_and_dropped_items_to_stderr(p):
    r = subprocess.run(
        [sys.executable, str(FLOW_PY), "export", str(p), "--lang", "en"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert r.stdout.startswith("Start at `a`.")
    assert "dropped information:" in r.stderr and "max_visits 3" in r.stderr
    assert "dropped" not in r.stdout


# --- round trip: the symbols match what lint / dry-run / graph report ---------


def edges_from_graph(mermaid: str) -> set[tuple[str, str, str]]:
    out = set()
    for m in re.finditer(
        r"^  n_(\w+) (?:-->\|(\w+)\||-\.->\|max (\d+)\||-->) n_(\w+)$",
        mermaid,
        re.MULTILINE,
    ):
        src, label, limit, dst = m.groups()
        out.add((src, label or (f"max {limit}" if limit else ""), dst))
    return out


def edges_from_export(parsed: dict) -> set[tuple[str, str, str]]:
    out = set()
    for sid, st in parsed["states"].items():
        out |= {(sid, label, dst) for label, dst, _ in st["choices"]}
        if st["goto"]:
            out.add((sid, "", st["goto"]))
        if "limit" in st:
            out.add((sid, f"max {st['limit'][0]}", st["limit"][1]))
    return out


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize(
    "path", REAL_DEFS, ids=lambda p: f"{p.parent.parent.parent.name}/{p.parent.name}"
)
def test_round_trip_matches_lint_graph_and_dry_run(flow, path, lang):
    assert flow.lint(path) == [] or all(i.level != "error" for i in flow.lint(path))
    parsed = parse_export(flow.export_skill(path, lang)[0])
    defn = flow.load_definition(path)
    # same states, same start, same transitions and limits
    assert parsed["start"] == defn.start
    assert list(parsed["states"]) == list(defn.states)
    assert edges_from_export(parsed) == edges_from_graph(flow.graph_mermaid(path))
    # same choice labels and wording as the steps the LLM sees
    dry = flow.dry_run(path, None)
    for sid, st in parsed["states"].items():
        assert f"[{sid}] (run:" in dry
        for label, _, when in st["choices"]:
            assert f"--result {label}" in dry and f": {when}" in dry
    ends = {sid for sid, st in parsed["states"].items() if st["end"]}
    assert ends == {sid for sid, s in defn.states.items() if s.end}
