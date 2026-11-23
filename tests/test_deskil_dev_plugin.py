"""Tests for the deskil-dev plugin: packaging, skills and flow definitions."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "plugins" / "deskil-dev"
SKILLS = ["add", "prio", "decide", "impl", "triage-rejected"]
PRESENT = [s for s in SKILLS if (DEV / "skills" / s).is_dir()]
ALLOWED_TOOLS = "Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*), Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py:*)"


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", f"{path} has no frontmatter"
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


def run_flow(*args, cwd):
    env = {
        k: v for k, v in os.environ.items() if k not in ("FLOW_CMD", "FLOW_STATE_DIR")
    }
    return subprocess.run(
        [sys.executable, str(DEV / "scripts" / "flow.py"), *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def dry_run(skill, results, cwd):
    res = run_flow(
        "dry-run",
        DEV / "skills" / skill / "flow.toml",
        "--results",
        ",".join(results),
        cwd=cwd,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    return res.stdout


def visited(out: str) -> list[str]:
    """State ids in the order a dry-run printed them."""
    return [
        line[1 : line.index("]")]
        for line in out.splitlines()
        if line.startswith("[") and "(run: dry-run)" in line
    ]


# --- packaging -------------------------------------------------------------


def test_marketplace_lists_deskil_dev():
    market = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    entry = next(p for p in market["plugins"] if p["name"] == "deskil-dev")
    assert entry["source"] == "./plugins/deskil-dev"
    assert entry["description"]


def test_plugin_json_names_deskil_dev():
    data = json.loads(
        (DEV / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert data["name"] == "deskil-dev" and data["license"] and data["description"]
    # version is omitted on purpose: the commit SHA is used as the version
    assert "version" not in data


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
    assert visited(dry_run("add", ["new", "ok"], tmp_path)) == [
        "prepare",
        "check_dup",
        "write",
        "lint",
        "report",
    ]
    assert visited(dry_run("add", ["duplicate", "ok"], tmp_path)) == [
        "prepare",
        "check_dup",
        "update_existing",
        "lint",
        "report",
    ]


def test_add_lint_failures_end_in_report_fail(tmp_path):
    out = dry_run("add", ["new", "errors", "errors", "errors"], tmp_path)
    assert visited(out)[-1] == "report_fail"
    assert visited(out).count("fix") == 2
    assert out.endswith("Flow complete.\n")


def test_prioritize_happy_path(tmp_path):
    out = dry_run("prio", ["approved", "ok"], tmp_path)
    assert visited(out) == ["survey", "propose", "confirm", "apply", "lint", "report"]
    assert out.endswith("Flow complete.\n")


def test_prioritize_revision_limit_leaves_the_backlog_unchanged(tmp_path):
    out = dry_run("prio", ["revise", "revise", "revise"], tmp_path)
    assert visited(out)[-1] == "report_unchanged"
    assert "apply" not in visited(out)


def test_prioritize_lint_failures_end_unchanged_report(tmp_path):
    out = dry_run("prio", ["approved", "errors", "errors", "errors"], tmp_path)
    assert visited(out)[-1] == "report_unchanged"
    assert visited(out).count("fix_prio") == 2


def test_decide_paths(tmp_path):
    head = ["pick", "investigate", "options", "confirm"]
    out = dry_run("decide", ["found", "ready", "done", "ok_ready"], tmp_path)
    assert visited(out) == head + [
        "record",
        "write_decision",
        "record",
        "lint",
        "report_ready",
    ]
    out = dry_run("decide", ["found", "dropped", "done", "ok_not_ready"], tmp_path)
    assert visited(out) == head + ["record", "drop", "record", "lint", "report"]
    out = dry_run("decide", ["found", "defer", "done", "ok_not_ready"], tmp_path)
    assert visited(out) == head + ["record", "note_open", "record", "lint", "report"]
    assert visited(dry_run("decide", ["none"], tmp_path)) == ["pick", "report_none"]


def test_decide_mixed_outcomes_are_recorded_one_by_one(tmp_path):
    choices = ["found", "ready", "dropped", "defer", "done", "ok_ready"]
    out = dry_run("decide", choices, tmp_path)
    assert visited(out)[4:] == [
        "record",
        "write_decision",
        "record",
        "drop",
        "record",
        "note_open",
        "record",
        "lint",
        "report_ready",
    ]


def test_decide_lint_failures_end_in_report_fail(tmp_path):
    choices = ["found", "ready", "done", "errors", "errors", "errors"]
    out = dry_run("decide", choices, tmp_path)
    assert visited(out)[-1] == "report_fail"


def test_decide_batch_consults_items_with_open_points_one_by_one():
    import tomllib

    flow = tomllib.loads((DEV / "skills" / "decide" / "flow.toml").read_text())
    options = flow["states"]["options"]["prompt"]
    confirm = flow["states"]["confirm"]["prompt"]
    # An item with an open point is discussed one at a time, with options and trade-offs.
    assert "one at a time" in options
    assert "open point" in options
    assert "trade-offs" in options
    # Only items with a clear approach go into the table.
    assert "already clear" in options
    # Defer needs a real reason; "needs discussion" is not one.
    assert "real reason" in options
    assert "not a reason" in options
    # Confirm asks for a choice on each consulted item, separately from the table.
    assert "one at a time" in confirm
    assert "which option" in confirm
    skill = (DEV / "skills" / "decide" / "SKILL.md").read_text()
    assert "one at a time" in skill
    assert "real reason" in skill


def test_implement_happy_path_order(tmp_path):
    out = dry_run("impl", ["found", "pass", "skip"], tmp_path)
    assert visited(out) == [
        "pick",
        "prepare",
        "plan",
        "implement",
        "verify",
        "classify",
        "finish_backlog",
        "commit",
        "open_pr",
        "back_to_default",
        "report",
    ]
    assert out.endswith("Flow complete.\n")


TAIL = ["finish_backlog", "commit", "open_pr", "back_to_default", "report"]
HEAD = ["pick", "prepare", "plan", "implement", "verify", "classify"]


def test_implement_review_without_security_or_fixes(tmp_path):
    out = dry_run(
        "impl", ["found", "pass", "review", "no_security", "not_fixed"], tmp_path
    )
    assert visited(out) == [*HEAD, "review", "triage", "record_rejected", *TAIL]


def test_implement_review_with_security(tmp_path):
    out = dry_run(
        "impl", ["found", "pass", "review", "security", "not_fixed"], tmp_path
    )
    assert visited(out) == [
        *HEAD,
        "review",
        "security_review",
        "triage",
        "record_rejected",
        *TAIL,
    ]


def test_implement_review_with_fixes_reviews_once(tmp_path):
    out = dry_run(
        "impl", ["found", "pass", "review", "no_security", "fixed", "pass"], tmp_path
    )
    seen = visited(out)
    assert seen.count("review") == 1 and seen.count("triage") == 1
    assert seen[-(len(TAIL) + 1) :] == ["record_rejected", *TAIL]
    assert seen[: len(HEAD) + 3] == [*HEAD, "review", "triage", "verify"]


def test_implement_review_failure_after_fix_uses_the_fix_limit(tmp_path):
    out = dry_run(
        "impl",
        ["found", "pass", "review", "no_security", "fixed", "fail", "fail", "fail"],
        tmp_path,
    )
    assert visited(out)[-1] == "report_fail"
    assert "open_pr" not in visited(out)


def test_classify_sees_committed_and_uncommitted_changes():
    classify = flow_states("impl")["classify"]
    # The work may already be committed (plans tell the implementer to commit per task).
    assert classify["run"] == ["git", "diff", "--name-status", "origin/HEAD"]
    assert classify["max_visits"] == 1
    assert classify["on_exceed"] == "record_rejected"
    prompt = classify["prompt"]
    assert "untracked" in prompt  # new files are not in the diff
    assert "worktree" in prompt  # the command may have run in another tree
    assert "empty" in prompt  # an empty result must not mean "skip"
    assert (
        "reached again" not in prompt
    )  # the second arrival is redirected and never shown


def test_security_review_cannot_stall_the_flow():
    state = flow_states("impl")["security_review"]
    assert "choices" not in state and state["goto"] == "triage"
    prompt = state["prompt"]
    assert "security-review" in prompt
    assert (
        "not the end" in prompt
        and "do not ask" in prompt.lower()
        and "`next`" in prompt
    )


def test_review_prompt_names_the_reviews():
    prompt = flow_states("impl")["review"]["prompt"]
    for name in ("code-review", "simplify", "deskil:flow-review"):
        assert name in prompt
    assert "do not decide" in prompt.lower()


def test_triage_prompt_fixes_once():
    prompt = flow_states("impl")["triage"]["prompt"]
    assert "once" in prompt and "out of scope" in prompt


def test_triage_writes_rejected_findings_to_the_file_at_once():
    # The list must not live only in the conversation (it is lost on compaction or report_fail).
    prompt = flow_states("impl")["triage"]["prompt"]
    assert "docs/REVIEW-REJECTED.md" in prompt


def test_security_review_handles_an_empty_report():
    assert "no findings" in flow_states("impl")["security_review"]["prompt"].lower()


def test_the_work_is_committed_once_before_the_pr():
    states = flow_states("impl")
    assert states["record_rejected"]["goto"] == "finish_backlog"
    assert states["finish_backlog"]["goto"] == "commit"
    assert states["commit"]["goto"] == "open_pr"
    assert "--pr" not in states["finish_backlog"]["prompt"]
    assert "do not commit" in states["record_rejected"]["prompt"].lower()
    assert "do not commit" in states["finish_backlog"]["prompt"].lower()
    assert "one commit" in states["commit"]["prompt"]


def test_record_rejected_writes_the_file_in_the_projects_language():
    prompt = flow_states("impl")["record_rejected"]["prompt"]
    assert "docs/REVIEW-REJECTED.md" in prompt and "nothing" in prompt.lower()
    assert (
        "Japanese" not in prompt
    )  # the language comes from the project's rules for docs
    assert "language" in prompt


def prepare_step(tmp_path):
    out = dry_run("impl", ["found"], tmp_path)
    return out.split("[prepare]", 1)[1].split("[plan]", 1)[0]


def test_implement_prepare_branches_from_a_fetched_origin(tmp_path):
    step = prepare_step(tmp_path)
    assert "git fetch origin" in step
    assert "git symbolic-ref --short refs/remotes/origin/HEAD" in step
    assert "git switch -c backlog/<ID> origin/<default branch> --no-track" in step
    assert "slug" not in step
    assert "clean" in step  # a dirty working tree still stops the flow


def test_implement_prepare_does_not_rely_on_a_local_default_branch(tmp_path):
    step = prepare_step(tmp_path)
    assert "up to date" not in step
    assert "pull" not in step.replace("pull request", "")


def test_implement_failure_limit_skips_the_pr(tmp_path):
    out = dry_run("impl", ["found", "fail", "fail", "fail"], tmp_path)
    assert visited(out)[-1] == "report_fail"
    assert visited(out).count("fix") == 2
    assert "open_pr" not in visited(out)


def test_implement_with_nothing_ready_offers_decide_then_stops_on_no(tmp_path):
    out = dry_run("impl", ["none", "no"], tmp_path)
    assert visited(out) == ["pick", "offer_decide", "report_none"]


def test_implement_decides_a_todo_and_goes_on_to_implement(tmp_path):
    choices = ["none", "yes", "found", "ready", "done", "ok_ready", "pass", "skip"]
    out = visited(dry_run("impl", choices, tmp_path))
    assert out[:2] == ["pick", "offer_decide"]
    assert out[2:4] == ["decide__pick", "decide__investigate"]
    i = out.index("decide__lint")
    assert out[i + 1 : i + 4] == ["after_decide", "prepare", "plan"]
    assert out[-1] == "report"


@pytest.mark.parametrize(
    ("choices", "end"),
    [
        (["found", "dropped", "done", "ok_not_ready"], "report_none"),
        (["none"], "report_none"),
        (
            ["found", "ready", "done", "errors", "errors", "errors"],
            "report_decide_fail",
        ),
    ],
)
def test_implement_ends_when_decide_makes_nothing_ready(tmp_path, choices, end):
    out = visited(dry_run("impl", ["none", "yes", *choices], tmp_path))
    assert out[-1] == end
    assert "prepare" not in out


def test_implement_prepare_allows_only_the_decided_backlog_change(tmp_path):
    step = prepare_step(tmp_path)
    assert "docs/BACKLOG.md" in step and "stop" in step


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
    assert (
        "`backlog.py <args>` means `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py <args>`"
        in text
    )


@pytest.mark.parametrize("skill", PRESENT)
def test_flow_lints_clean(skill, tmp_path):
    res = run_flow("lint", DEV / "skills" / skill / "flow.toml", cwd=tmp_path)
    assert res.returncode == 0 and res.stdout == "", res.stdout + res.stderr


# --- fixed commands run by the flow (${DEF_DIR}) ----------------------------

BACKLOG_PY = ["uv", "run", "${DEF_DIR}/../../scripts/backlog.py"]
RUN_STATES = [
    ("add", "lint", ["lint"]),
    ("add", "write", ["next-id"]),
    ("decide", "lint", ["lint"]),
    ("prio", "lint", ["lint"]),
    ("prio", "survey", ["list"]),
    ("triage-rejected", "lint", ["lint"]),
]


def flow_states(skill: str) -> dict:
    import tomllib

    return tomllib.loads(
        (DEV / "skills" / skill / "flow.toml").read_text(encoding="utf-8")
    )["states"]


@pytest.mark.parametrize(("skill", "state", "args"), RUN_STATES)
def test_fixed_commands_are_run_by_the_flow(skill, state, args):
    assert flow_states(skill)[state]["run"] == [*BACKLOG_PY, *args]


@pytest.mark.parametrize(
    ("skill", "state"),
    [("decide", "pick"), ("impl", "pick"), ("impl", "prepare"), ("impl", "verify")],
)
def test_commands_not_in_scope_are_not_run(skill, state):
    assert "run" not in flow_states(skill)[state]


@pytest.mark.parametrize(("skill", "state", "args"), RUN_STATES)
def test_run_target_exists(skill, state, args):
    target = flow_states(skill)[state]["run"][2].replace(
        "${DEF_DIR}", str(DEV / "skills" / skill)
    )
    assert Path(target).resolve().is_file()


@pytest.mark.parametrize(("skill", "state", "args"), RUN_STATES)
def test_run_commands_work_in_the_project(skill, state, args):
    argv = [
        a.replace("${DEF_DIR}", str(DEV / "skills" / skill))
        for a in flow_states(skill)[state]["run"]
    ]
    res = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    if args == ["next-id"]:
        assert res.stdout.startswith("B-")


@pytest.mark.parametrize(("skill", "state", "args"), RUN_STATES)
def test_prompt_points_at_the_command_below(skill, state, args):
    # The step prints the prompt first and the command result after it.
    prompt = flow_states(skill)[state]["prompt"]
    assert "command above" not in prompt
    assert "command below" in prompt


# --- triage-rejected ---------------------------------------------------------


def test_triage_rejected_empty_file_ends_without_changes(tmp_path):
    out = dry_run("triage-rejected", ["empty"], tmp_path)
    assert visited(out) == ["read", "report_empty"]


def test_triage_rejected_happy_path(tmp_path):
    out = dry_run("triage-rejected", ["entries", "ok"], tmp_path)
    assert visited(out) == ["read", "judge", "apply", "lint", "report"]


def test_triage_rejected_lint_failures_end_in_report_fail(tmp_path):
    out = dry_run(
        "triage-rejected", ["entries", "errors", "errors", "errors"], tmp_path
    )
    assert visited(out)[-1] == "report_fail"


def test_triage_rejected_judge_rules():
    states = flow_states("triage-rejected")
    prompt = states["judge"]["prompt"]
    assert "deskil-dev:add" in states["apply"]["prompt"]
    assert "twice" in prompt or "2" in prompt  # repeated findings raise priority
    assert "docs/REVIEW-REJECTED.md" in states["apply"]["prompt"]
    assert "history" in states["apply"]["prompt"].lower()  # deleted entries stay in git
