import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "plugins" / "deskil"
SKILLS = ["flow-author", "flow-review", "flow-convert", "flow-export"]
INSTALL = "uv tool install git+https://github.com/wtnb75/deskil"


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", f"{path} has no frontmatter"
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


def test_marketplace_lists_deskil():
    market = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    entry = next(p for p in market["plugins"] if p["name"] == "deskil")
    assert entry["source"] == "./plugins/deskil"


def test_plugin_json_names_deskil():
    data = json.loads(
        (CORE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert data["name"] == "deskil" and data["license"]
    # version is omitted on purpose: the commit SHA is used as the version
    assert "version" not in data


def test_no_bundled_engine():
    link = CORE / "scripts" / "flow.py"
    assert not link.exists() and not link.is_symlink()


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_frontmatter(skill):
    fm = frontmatter(CORE / "skills" / skill / "SKILL.md")
    assert fm["name"] == skill
    assert fm["description"]
    assert fm["allowed-tools"] == "Bash(deskil --version), Bash(deskil flow:*)"


@pytest.mark.parametrize("skill", SKILLS)
def test_skills_check_the_install_first(skill):
    text = (CORE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    body = text.split("\n---\n", 1)[1]  # the frontmatter's description is prose
    assert "deskil --version" in body and INSTALL in body
    # the check comes before the first command of the skill
    assert body.index("deskil --version") < body.index("deskil flow ")


def test_no_engine_path_left():
    for path in CORE.rglob("*"):
        if path.suffix in (".md", ".toml"):
            assert "scripts/flow.py" not in path.read_text(encoding="utf-8"), path


def test_author_skill_covers_the_authoring_commands():
    text = (CORE / "skills" / "flow-author" / "SKILL.md").read_text(encoding="utf-8")
    for needle in (
        "deskil flow lint",
        "deskil flow dry-run",
        "deskil flow rename",
        "{ file =",
    ):
        assert needle in text


def test_author_wire_up_recommends_the_command_not_a_symlink():
    text = (CORE / "skills" / "flow-author" / "SKILL.md").read_text(encoding="utf-8")
    wire = text.split("## 5.", 1)[1]
    assert "Bash(deskil flow:*)" in wire and "Bash(deskil --version)" in wire
    assert "deskil --version`" in wire
    assert "symlink" not in wire


@pytest.mark.parametrize("skill", ["flow-convert", "flow-export"])
def test_flow_driven_skill_runs_its_definition(skill):
    text = (CORE / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert f"deskil flow start ${{CLAUDE_PLUGIN_ROOT}}/skills/{skill}/flow.toml" in text
    assert "Flow complete." in text
    assert (CORE / "skills" / skill / "flow.toml").is_file()


def test_convert_skill_covers_split_rule_and_verification():
    text = (CORE / "skills" / "flow-convert" / "flow.toml").read_text(encoding="utf-8")
    for needle in (
        "deskil flow lint",
        "deskil flow dry-run",
        "flow-author",
        "correspondence table",
    ):
        assert needle in text


def test_convert_wire_up_recommends_the_command_not_a_symlink():
    text = (CORE / "skills" / "flow-convert" / "flow.toml").read_text(encoding="utf-8")
    wire = text.split("[states.rewrite]", 1)[1].split("[states.report]", 1)[0]
    assert "Bash(deskil flow:*)" in wire and "Bash(deskil --version)" in wire
    assert "deskil --version`" in wire
    assert "symlink" not in wire


def test_review_skill_covers_review_and_debug_commands():
    text = (CORE / "skills" / "flow-review" / "SKILL.md").read_text(encoding="utf-8")
    for needle in (
        "deskil flow lint",
        "deskil flow dry-run",
        "--results",
        "deskil flow status",
    ):
        assert needle in text


def test_export_skill_covers_export_report_and_round_trip():
    text = (CORE / "skills" / "flow-export" / "flow.toml").read_text(encoding="utf-8")
    for needle in (
        "deskil flow export",
        "deskil flow lint",
        "deskil flow graph",
        "deskil flow dry-run",
        "dropped information",
        "max_visits",
        "delegate",
        "--lang",
    ):
        assert needle in text


def test_export_removes_the_deskil_entry_and_keeps_no_symlink_step():
    text = (CORE / "skills" / "flow-export" / "flow.toml").read_text(encoding="utf-8")
    write = text.split("[states.write_skill]", 1)[1].split("[states.report_lost]", 1)[0]
    assert "Bash(deskil flow:*)" in write and "allowed-tools" in write
    assert "symlink" not in write
