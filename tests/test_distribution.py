"""No plugin bundles the engine: skills call the installed `deskil` command."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
INSTALL = "uv tool install git+https://github.com/wtnb75/deskil"


def test_no_plugin_bundles_the_engine():
    # glob lists symlinks too, even broken ones
    assert list(PLUGINS.glob("*/scripts/flow.py")) == []


def test_no_skill_text_points_at_the_bundled_engine():
    for pattern in ("**/SKILL.md", "**/flow.toml"):
        for path in PLUGINS.glob(pattern):
            assert "scripts/flow.py" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize(
    "skill", sorted(PLUGINS.glob("*/skills/*/SKILL.md")), ids=lambda p: p.parent.name
)
def test_every_deskil_flow_skill_checks_the_install(skill):
    body = skill.read_text(encoding="utf-8").split("\n---\n", 1)[1]
    if "deskil flow " not in body:
        pytest.skip("does not call the engine")
    assert "deskil --version" in body and INSTALL in body
