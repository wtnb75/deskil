"""No plugin bundles the engine: skills call the installed `deskil` command."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
INSTALL = "uv tool install git+https://github.com/wtnb75/deskil"
SKILL_FILES = sorted(PLUGINS.glob("*/skills/*/SKILL.md"))


def test_no_plugin_bundles_the_engine():
    # glob lists symlinks too, even broken ones
    assert list(PLUGINS.glob("*/scripts/flow.py")) == []


def test_no_skill_text_points_at_the_bundled_engine():
    for pattern in ("**/SKILL.md", "**/flow.toml"):
        for path in PLUGINS.glob(pattern):
            assert "scripts/flow.py" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_deskil_flow_skill_checks_the_install(skill):
    body = skill.read_text(encoding="utf-8").split("\n---\n", 1)[1]
    if "deskil flow " not in body:
        pytest.skip("does not call the engine")
    assert "deskil --version" in body and INSTALL in body


@pytest.mark.parametrize("skill", SKILL_FILES, ids=lambda p: p.parent.name)
def test_the_install_check_is_allowed_without_a_prompt(skill):
    text = skill.read_text(encoding="utf-8")
    if "deskil flow " not in text.split("\n---\n", 1)[1]:
        pytest.skip("does not call the engine")
    allowed = next(
        line for line in text.splitlines() if line.startswith("allowed-tools:")
    )
    assert "Bash(deskil --version)" in allowed and "Bash(deskil flow:*)" in allowed


def test_templates_tell_converted_skills_to_allow_the_install_check():
    author = (PLUGINS / "deskil/skills/flow-author/SKILL.md").read_text(
        encoding="utf-8"
    )
    convert = (PLUGINS / "deskil/skills/flow-convert/flow.toml").read_text(
        encoding="utf-8"
    )
    assert "Bash(deskil --version)" in author.split("## 5.", 1)[1]
    assert "Bash(deskil --version)" in convert.split("[states.rewrite]", 1)[1]


def test_no_old_style_engine_command_is_left_in_skill_text():
    # `flow runs` is not a command any more; the engine is called as `deskil flow runs`.
    old = re.compile(
        r"`flow (start|next|status|runs|gc|stats|lint|fmt|rename|dry-run|export|graph|new|test)\b"
    )
    for pattern in ("**/SKILL.md", "**/flow.toml"):
        for path in PLUGINS.glob(pattern):
            found = old.search(path.read_text(encoding="utf-8"))
            assert found is None, f"{path}: {found.group(0)}"
