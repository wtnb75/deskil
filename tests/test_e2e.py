"""End-to-end: run the sample flow of feature-a with the engine."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "feature-a"
ENGINE = ROOT / "shared" / "flow" / "flow.py"
DEFN = PLUGIN / "skills" / "review-loop" / "flow.toml"
SKILL = PLUGIN / "skills" / "review-loop" / "SKILL.md"


def run_flow(args, cwd):
    env = {
        k: v for k, v in os.environ.items() if k not in ("FLOW_CMD", "FLOW_STATE_DIR")
    }
    return subprocess.run(
        [sys.executable, str(ENGINE), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def hint_args(out: str, label: str | None) -> list[str]:
    """Extract the arguments of the printed `next` hint (everything after the script path)."""
    pattern = (
        r"uv run "
        + re.escape(str(ENGINE))
        + r" (next \S+"
        + (rf" --result {label}" if label else "")
        + r")\s*(?:\n|:)"
    )
    m = re.search(pattern, out)
    assert m, f"no next hint for {label!r} in:\n{out}"
    return m.group(1).split()


def test_engine_is_executable():
    assert os.access(ROOT / "shared" / "flow" / "flow.py", os.X_OK)


def test_sample_definition_lints_clean(tmp_path):
    res = run_flow(["lint", str(DEFN)], tmp_path)
    assert res.returncode == 0 and res.stdout == "", res.stdout + res.stderr


def test_skill_runs_the_deskil_command():
    text = SKILL.read_text(encoding="utf-8")
    assert "allowed-tools: Bash(deskil flow:*)" in text
    assert "deskil flow start" in text and "Flow complete." in text


def test_gitignore_excludes_run_state():
    assert ".flow/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_review_loop_end_to_end(tmp_path):
    res = run_flow(["start", str(DEFN)], tmp_path)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert out.startswith("[run_tests]")

    # fail -> fix (1st) -> run_tests -> fail -> fix (2nd) -> run_tests.
    # Each command comes from the hint printed by the previous step.
    steps = [
        ("fail", "[fix]"),
        (None, "[run_tests]"),
        ("fail", "[fix]"),
        (None, "[run_tests]"),
    ]
    for label, expected_state in steps:
        res = run_flow(hint_args(out, label), tmp_path)
        assert res.returncode == 0, res.stderr
        out = res.stdout
        assert out.startswith(expected_state), out

    # A third failure would need a third fix: on_exceed sends the run to report_fail.
    res = run_flow(hint_args(out, "fail"), tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stdout.startswith("[report_fail]")
    assert res.stdout.endswith("Flow complete.\n")

    runs = list((tmp_path / ".flow" / "runs").glob("*.json"))
    assert len(runs) == 1


@pytest.mark.parametrize("label,final", [("pass", "[report]")])
def test_pass_path_ends_at_report(tmp_path, label, final):
    out = run_flow(["start", str(DEFN)], tmp_path).stdout
    res = run_flow(hint_args(out, label), tmp_path)
    assert res.stdout.startswith(final) and res.stdout.endswith("Flow complete.\n")
