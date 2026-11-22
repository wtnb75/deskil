"""Tests for the deskil-dev plugin: packaging, skills and flow definitions."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "plugins" / "deskil-dev"
SKILLS = ["backlog-add", "backlog-prioritize", "backlog-decide", "backlog-implement"]
PRESENT = [s for s in SKILLS if (DEV / "skills" / s).is_dir()]
ALLOWED_TOOLS = (
    "Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*), Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py:*)"
)


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", f"{path} has no frontmatter"
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


def run_flow(*args, cwd):
    env = {k: v for k, v in os.environ.items() if k not in ("FLOW_CMD", "FLOW_STATE_DIR")}
    return subprocess.run(
        [sys.executable, str(DEV / "scripts" / "flow.py"), *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def dry_run(skill, results, cwd):
    res = run_flow("dry-run", DEV / "skills" / skill / "flow.toml", "--results", ",".join(results), cwd=cwd)
    assert res.returncode == 0, res.stdout + res.stderr
    return res.stdout


def visited(out: str) -> list[str]:
    """State ids in the order a dry-run printed them."""
    return [line[1 : line.index("]")] for line in out.splitlines() if line.startswith("[") and "(run: dry-run)" in line]


# --- packaging -------------------------------------------------------------


def test_marketplace_lists_deskil_dev():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    entry = next(p for p in market["plugins"] if p["name"] == "deskil-dev")
    assert entry["source"] == "./plugins/deskil-dev"
    assert entry["description"]


def test_plugin_json_names_deskil_dev():
    data = json.loads((DEV / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert data["name"] == "deskil-dev" and data["version"] and data["description"]


@pytest.mark.parametrize(
    "script,target",
    [("flow.py", "shared/flow/flow.py"), ("backlog.py", "shared/backlog/backlog.py")],
)
def test_scripts_are_relative_symlinks_into_shared(script, target):
    link = DEV / "scripts" / script
    assert link.is_symlink() and not os.path.isabs(os.readlink(link))
    assert link.resolve() == (ROOT / target).resolve()


# --- flow paths ------------------------------------------------------------


def test_add_happy_and_duplicate_paths(tmp_path):
    assert visited(dry_run("backlog-add", ["new", "ok"], tmp_path)) == ["check_dup", "write", "lint", "report"]
    assert visited(dry_run("backlog-add", ["duplicate", "ok"], tmp_path)) == [
        "check_dup",
        "update_existing",
        "lint",
        "report",
    ]


def test_add_lint_failures_end_in_report_fail(tmp_path):
    out = dry_run("backlog-add", ["new", "errors", "errors", "errors"], tmp_path)
    assert visited(out)[-1] == "report_fail"
    assert visited(out).count("fix") == 2
    assert out.endswith("Flow complete.\n")


def test_prioritize_happy_path(tmp_path):
    out = dry_run("backlog-prioritize", ["approved", "ok"], tmp_path)
    assert visited(out) == ["survey", "propose", "confirm", "apply", "lint", "report"]
    assert out.endswith("Flow complete.\n")


def test_prioritize_revision_limit_leaves_the_backlog_unchanged(tmp_path):
    out = dry_run("backlog-prioritize", ["revise", "revise", "revise"], tmp_path)
    assert visited(out)[-1] == "report_unchanged"
    assert "apply" not in visited(out)


def test_prioritize_lint_failures_end_unchanged_report(tmp_path):
    out = dry_run("backlog-prioritize", ["approved", "errors", "errors", "errors"], tmp_path)
    assert visited(out)[-1] == "report_unchanged"
    assert visited(out).count("fix_prio") == 2


# --- skills (the ones that exist so far) -----------------------------------


@pytest.mark.parametrize("skill", PRESENT)
def test_skill_frontmatter(skill):
    fm = frontmatter(DEV / "skills" / skill / "SKILL.md")
    assert fm["name"] == skill
    assert fm["description"]
    assert fm["allowed-tools"] == ALLOWED_TOOLS


@pytest.mark.parametrize("skill", PRESENT)
def test_skill_runs_the_flow(skill):
    text = (DEV / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert f"${{CLAUDE_PLUGIN_ROOT}}/skills/{skill}/flow.toml" in text
    assert "flow.py start" in text and "Flow complete." in text
    # The engine does not expand paths in prompts, so SKILL.md tells the LLM what `backlog.py` means.
    assert "`backlog.py <args>` means `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py <args>`" in text


@pytest.mark.parametrize("skill", PRESENT)
def test_flow_lints_clean(skill, tmp_path):
    res = run_flow("lint", DEV / "skills" / skill / "flow.toml", cwd=tmp_path)
    assert res.returncode == 0 and res.stdout == "", res.stdout + res.stderr
