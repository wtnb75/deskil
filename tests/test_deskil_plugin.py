import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "plugins" / "deskil"
SKILLS = ["flow-author", "flow-review", "flow-convert"]


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", f"{path} has no frontmatter"
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


def test_marketplace_lists_deskil():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    entry = next(p for p in market["plugins"] if p["name"] == "deskil")
    assert entry["source"] == "./plugins/deskil"


def test_plugin_json_names_deskil():
    data = json.loads((CORE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["name"] == "deskil" and data["version"]


def test_engine_is_bundled_by_relative_symlink():
    link = CORE / "scripts" / "flow.py"
    assert link.is_symlink() and not os.path.isabs(os.readlink(link))
    assert link.resolve() == (ROOT / "shared" / "flow" / "flow.py").resolve()


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_frontmatter(skill):
    fm = frontmatter(CORE / "skills" / skill / "SKILL.md")
    assert fm["name"] == skill
    assert fm["description"]
    assert fm["allowed-tools"] == "Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)"


def test_author_skill_covers_the_authoring_commands():
    text = (CORE / "skills" / "flow-author" / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("flow.py lint", "flow.py dry-run", "flow.py rename", "{ file ="):
        assert needle in text


def test_convert_skill_covers_split_rule_and_verification():
    text = (CORE / "skills" / "flow-convert" / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("flow.py lint", "flow.py dry-run", "flow-author", "correspondence table"):
        assert needle in text


def test_review_skill_covers_review_and_debug_commands():
    text = (CORE / "skills" / "flow-review" / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("flow.py lint", "flow.py dry-run", "--results", "flow.py status"):
        assert needle in text
