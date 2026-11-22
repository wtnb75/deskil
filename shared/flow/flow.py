#!/usr/bin/env python3
"""flow: a deterministic state-machine runner for step-by-step skills.

Single file, standard library only (Python 3.11+).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import string
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# errors and issues
# ---------------------------------------------------------------------------


class FlowError(Exception):
    """A user-facing error. The CLI prints it without a traceback."""


@dataclass(frozen=True)
class Issue:
    """One finding reported by the linter."""

    level: str  # "error" or "warning"
    code: str
    where: str
    message: str


# ---------------------------------------------------------------------------
# reading definitions
# ---------------------------------------------------------------------------


def read_toml(path: Path) -> dict:
    """Parse a TOML file, converting I/O and syntax errors into FlowError."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise FlowError(f"{path}: cannot read file ({e.strerror})") from e
    except tomllib.TOMLDecodeError as e:
        raise FlowError(f"{path}: {e}") from e


# ---------------------------------------------------------------------------
# linter: schema checks
# ---------------------------------------------------------------------------

ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LABEL_RE = re.compile(r"^[A-Za-z0-9_]+$")

TOP_KEYS = {"schema", "start", "notes", "states"}
NOTES_KEYS = {"always", "common"}
STATE_KEYS = {"prompt", "notes", "goto", "choices", "end", "max_visits", "on_exceed"}
CHOICE_KEYS = {"label", "when", "goto"}
RESERVED_KEYS = {"delegate"}  # reserved for step delegation; not supported yet


def _err(issues: list[Issue], code: str, where: str, message: str) -> None:
    issues.append(Issue("error", code, where, message))


def _check_keys(obj: dict, allowed: set[str], where: str, issues: list[Issue]) -> None:
    for key in obj:
        if key in RESERVED_KEYS:
            _err(issues, "reserved-key", where, f"'{key}' is reserved and not supported yet")
        elif key not in allowed:
            _err(issues, "unknown-key", where, f"unknown key '{key}'")


def _check_text(value: object, where: str, base_dir: Path, issues: list[Issue]) -> None:
    """A text value is a string or a table of the form { file = "relative/path" }."""
    if isinstance(value, str):
        return
    if not (isinstance(value, dict) and set(value) == {"file"} and isinstance(value["file"], str)):
        _err(issues, "type", where, 'expected a string or { file = "path" }')
        return
    rel = Path(value["file"])
    base = base_dir.resolve()
    target = (base / rel).resolve()
    if rel.is_absolute() or not target.is_relative_to(base):
        _err(issues, "file-outside", where, f"'{value['file']}' is outside the definition directory")
    elif not target.is_file():
        _err(issues, "file-missing", where, f"file not found: {value['file']}")


def _check_notes(notes: object, base_dir: Path, issues: list[Issue]) -> set[str]:
    """Check the [notes] table and return the names defined in notes.common."""
    common_names: set[str] = set()
    if not isinstance(notes, dict):
        _err(issues, "type", "notes", "notes must be a table")
        return common_names
    _check_keys(notes, NOTES_KEYS, "notes", issues)
    always = notes.get("always", [])
    if not isinstance(always, list):
        _err(issues, "type", "notes.always", "notes.always must be a list")
    else:
        for i, item in enumerate(always):
            _check_text(item, f"notes.always[{i}]", base_dir, issues)
    common = notes.get("common", {})
    if not isinstance(common, dict):
        _err(issues, "type", "notes.common", "notes.common must be a table")
    else:
        for name, item in common.items():
            common_names.add(name)
            _check_text(item, f"notes.common.{name}", base_dir, issues)
    return common_names


def _check_choices(
    choices: object, where: str, state_ids: set[str], base_dir: Path, issues: list[Issue]
) -> None:
    if not isinstance(choices, list) or not choices:
        _err(issues, "type", where, "choices must be a non-empty list of tables")
        return
    seen: set[str] = set()
    for i, ch in enumerate(choices):
        cw = f"{where}.choices[{i}]"
        if not isinstance(ch, dict):
            _err(issues, "type", cw, "a choice must be a table")
            continue
        _check_keys(ch, CHOICE_KEYS, cw, issues)
        label = ch.get("label")
        if not isinstance(label, str) or not LABEL_RE.match(label):
            _err(issues, "label-format", cw, f"label must match {LABEL_RE.pattern}: {label!r}")
        elif label in seen:
            _err(issues, "label-duplicate", cw, f"duplicate label '{label}'")
        else:
            seen.add(label)
        if "when" not in ch:
            _err(issues, "when-missing", cw, "a choice needs 'when' (the criterion)")
        else:
            _check_text(ch["when"], f"{cw}.when", base_dir, issues)
        goto = ch.get("goto")
        if goto not in state_ids:
            _err(issues, "missing-target", cw, f"goto target not found: {goto!r}")


def _check_state(
    sid: str, st: object, state_ids: set[str], common: set[str], base_dir: Path,
    issues: list[Issue],
) -> None:
    where = f"states.{sid}"
    if not ID_RE.match(sid):
        _err(issues, "id-format", where, f"state id must match {ID_RE.pattern}")
    if not isinstance(st, dict):
        _err(issues, "type", where, "a state must be a table")
        return
    _check_keys(st, STATE_KEYS, where, issues)

    if "prompt" not in st:
        _err(issues, "prompt-missing", where, "a state needs 'prompt'")
    else:
        _check_text(st["prompt"], f"{where}.prompt", base_dir, issues)

    if "notes" in st:
        names = st["notes"]
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            _err(issues, "type", f"{where}.notes", "notes must be a list of names")
        else:
            for n in names:
                if n not in common:
                    _err(issues, "note-undefined", f"{where}.notes", f"'{n}' is not in notes.common")

    is_end = st.get("end") is True
    if "end" in st and not isinstance(st["end"], bool):
        _err(issues, "type", f"{where}.end", "end must be true or false")
    if is_end and any(k in st for k in ("goto", "choices", "max_visits")):
        _err(issues, "end-with-transition", where, "an end state cannot have goto/choices/max_visits")
    else:
        count = sum(1 for k in ("goto", "choices") if k in st) + (1 if is_end else 0)
        if count != 1:
            _err(issues, "transition-count", where, "exactly one of goto / choices / end is required")

    if "goto" in st and st["goto"] not in state_ids:
        _err(issues, "missing-target", f"{where}.goto", f"goto target not found: {st['goto']!r}")
    if "choices" in st:
        _check_choices(st["choices"], where, state_ids, base_dir, issues)

    mv = st.get("max_visits")
    if "max_visits" in st and (type(mv) is not int or mv < 1):
        _err(issues, "type", f"{where}.max_visits", "max_visits must be an integer >= 1")
    if "max_visits" in st and "on_exceed" not in st and not is_end:
        _err(issues, "on-exceed-missing", where, "max_visits requires on_exceed")
    if "on_exceed" in st and st["on_exceed"] not in state_ids:
        _err(issues, "missing-target", f"{where}.on_exceed", f"on_exceed target not found: {st['on_exceed']!r}")


def lint_schema(raw: dict, base_dir: Path) -> list[Issue]:
    """Check structure and types of a parsed definition. Never raises."""
    issues: list[Issue] = []
    _check_keys(raw, TOP_KEYS, "(top level)", issues)

    if type(raw.get("schema")) is not int or raw.get("schema") != 1:
        _err(issues, "schema", "schema", "schema must be 1")

    common: set[str] = set()
    if "notes" in raw:
        common = _check_notes(raw["notes"], base_dir, issues)

    states = raw.get("states")
    if not isinstance(states, dict):
        _err(issues, "type", "states", "states must be a table of states")
        states = {}
    state_ids = set(states)

    start = raw.get("start")
    if not isinstance(start, str) or start not in state_ids:
        _err(issues, "start", "start", f"start must name an existing state: {start!r}")

    for sid, st in states.items():
        _check_state(sid, st, state_ids, common, base_dir, issues)
    return issues


# ---------------------------------------------------------------------------
# linter: graph checks
# ---------------------------------------------------------------------------


def _edges(st: dict) -> list[str]:
    """Targets reachable from one state: goto, every choice, and on_exceed."""
    out = []
    if "goto" in st:
        out.append(st["goto"])
    out.extend(ch["goto"] for ch in st.get("choices", []))
    if "on_exceed" in st:
        out.append(st["on_exceed"])
    return out


def _reachable(graph: dict[str, list[str]], roots: list[str]) -> set[str]:
    seen = set(roots)
    stack = list(roots)
    while stack:
        for nxt in graph.get(stack.pop(), []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _sccs(graph: dict[str, list[str]]) -> list[list[str]]:
    """Strongly connected components (iterative Kosaraju)."""
    order: list[str] = []
    seen: set[str] = set()
    for root in graph:
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(graph[root]))]
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append((nxt, iter(graph[nxt])))
                    break
            else:
                stack.pop()
                order.append(node)
    reverse: dict[str, list[str]] = {n: [] for n in graph}
    for n, targets in graph.items():
        for t in targets:
            reverse[t].append(n)
    comps: list[list[str]] = []
    assigned: set[str] = set()
    for root in reversed(order):
        if root in assigned:
            continue
        comp = []
        assigned.add(root)
        stack2 = [root]
        while stack2:
            node = stack2.pop()
            comp.append(node)
            for prev in reverse[node]:
                if prev not in assigned:
                    assigned.add(prev)
                    stack2.append(prev)
        comps.append(comp)
    return comps


def lint_graph(raw: dict) -> list[Issue]:
    """Check reachability and loops. Expects a definition that passed lint_schema."""
    issues: list[Issue] = []
    states: dict[str, dict] = raw["states"]
    graph = {sid: _edges(st) for sid, st in states.items()}

    reachable = _reachable(graph, [raw["start"]])
    for sid in states:
        if sid not in reachable:
            issues.append(
                Issue("error", "orphan", f"states.{sid}", "state is not reachable from start")
            )

    reverse: dict[str, list[str]] = {sid: [] for sid in states}
    for sid, targets in graph.items():
        for t in targets:
            reverse[t].append(sid)
    ends = [sid for sid, st in states.items() if st.get("end") is True]
    can_end = _reachable(reverse, ends)
    for sid in states:
        if sid in reachable and sid not in can_end:
            issues.append(
                Issue("error", "dead-end", f"states.{sid}", "no path from this state reaches an end state")
            )

    used = {n for st in states.values() for n in st.get("notes", [])}
    for name in raw.get("notes", {}).get("common", {}):
        if name not in used:
            issues.append(
                Issue("warning", "unused-note", f"notes.common.{name}", "note is not referenced by any state")
            )

    for sid, st in states.items():
        if len(st.get("choices", [])) == 1:
            issues.append(
                Issue("warning", "single-choice", f"states.{sid}", "only one choice; use goto instead")
            )

    reach_graph = {sid: graph[sid] for sid in states if sid in reachable}
    for comp in _sccs(reach_graph):
        is_cycle = len(comp) > 1 or comp[0] in graph[comp[0]]
        if is_cycle and not any("max_visits" in states[s] for s in comp):
            members = ", ".join(sorted(comp))
            issues.append(
                Issue(
                    "warning",
                    "unbounded-loop",
                    f"states.{sorted(comp)[0]}",
                    f"loop without max_visits ({members}); exit depends only on the LLM's choice",
                )
            )
    return issues


def lint(path: Path) -> list[Issue]:
    """Lint a definition file. Graph checks run only if the schema is clean."""
    raw = read_toml(path)
    issues = lint_schema(raw, path.resolve().parent)
    if not any(i.level == "error" for i in issues):
        issues += lint_graph(raw)
    return issues


def format_issue(issue: Issue) -> str:
    return f"{issue.level}[{issue.code}] {issue.where}: {issue.message}"


# ---------------------------------------------------------------------------
# loading definitions
# ---------------------------------------------------------------------------

Text = str | dict  # a string, or {"file": "relative/path"}


@dataclass(frozen=True)
class Choice:
    label: str
    when: Text
    goto: str


@dataclass(frozen=True)
class State:
    id: str
    prompt: Text
    notes: tuple[str, ...]
    goto: str | None
    choices: tuple[Choice, ...]
    end: bool
    max_visits: int | None
    on_exceed: str | None


@dataclass(frozen=True)
class Definition:
    path: Path
    base_dir: Path
    start: str
    always: tuple[Text, ...]
    common: dict[str, Text]
    states: dict[str, State]


def read_text_value(value: Text, base_dir: Path) -> str:
    """Return the text of a string or { file = ... } value (one trailing newline removed)."""
    if isinstance(value, str):
        return value
    path = base_dir / value["file"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise FlowError(f"{path}: cannot read file ({e.strerror})") from e
    except UnicodeDecodeError as e:
        raise FlowError(f"{path}: not valid UTF-8 ({e.reason})") from e
    return text[:-1] if text.endswith("\n") else text


def load_definition(path: Path) -> Definition:
    """Lint a definition and build it. Any lint error raises FlowError."""
    path = Path(path).resolve()
    issues = lint(path)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        lines = "\n".join(format_issue(i) for i in errors)
        raise FlowError(f"{path}: definition has errors\n{lines}")
    raw = read_toml(path)
    notes = raw.get("notes", {})
    states = {}
    for sid, st in raw["states"].items():
        states[sid] = State(
            id=sid,
            prompt=st["prompt"],
            notes=tuple(st.get("notes", [])),
            goto=st.get("goto"),
            choices=tuple(
                Choice(c["label"], c["when"], c["goto"]) for c in st.get("choices", [])
            ),
            end=st.get("end") is True,
            max_visits=st.get("max_visits"),
            on_exceed=st.get("on_exceed"),
        )
    return Definition(
        path=path,
        base_dir=path.parent,
        start=raw["start"],
        always=tuple(notes.get("always", [])),
        common=dict(notes.get("common", {})),
        states=states,
    )


# ---------------------------------------------------------------------------
# rendering a step for the LLM
# ---------------------------------------------------------------------------


def render_step(defn: Definition, state_id: str, run_id: str, cmd: str = "flow") -> str:
    """Render what the LLM sees for one state. Reads only the files that state needs."""
    st = defn.states[state_id]
    sections = [f"[{st.id}] (run: {run_id})\n{read_text_value(st.prompt, defn.base_dir)}"]

    notes: list[str] = []
    for item in [*defn.always, *(defn.common[n] for n in st.notes)]:
        text = read_text_value(item, defn.base_dir)
        if text not in notes:
            notes.append(text)
    if notes:
        sections.append("Notes:\n" + "\n".join(f"- {n}" for n in notes))

    if st.end:
        sections.append("Flow complete.")
    elif st.choices:
        width = max(len(c.label) for c in st.choices)
        lines = [
            f"  {cmd} next {run_id} --result {c.label.ljust(width)} : "
            f"{read_text_value(c.when, defn.base_dir)}"
            for c in st.choices
        ]
        header = "After finishing the work, report the result with one of the following:"
        sections.append("\n".join([header, *lines]))
    else:
        sections.append(f"After finishing the work, run:\n  {cmd} next {run_id}")
    return "\n\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# runs: state file and transitions
# ---------------------------------------------------------------------------

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class Run:
    run_id: str
    definition: str  # absolute path of the definition file
    definition_hash: str  # sha256 of the definition file's bytes
    current: str
    visits: dict[str, int]
    history: list[dict]  # {"state", "label", "at"}
    status: str  # "running" or "ended"


def _run_path(state_dir: Path, run_id: str) -> Path:
    return state_dir / f"{run_id}.json"


def _not_found(run_id: str, state_dir: Path) -> FlowError:
    return FlowError(f"run not found: {run_id} (looked in {state_dir})")


def load_run(state_dir: Path, run_id: str) -> Run:
    if not RUN_ID_RE.match(run_id):
        raise _not_found(run_id, state_dir)
    path = _run_path(state_dir, run_id)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise _not_found(run_id, state_dir) from None
    except OSError as e:
        raise FlowError(f"{path}: cannot read run file ({e.strerror})") from e
    try:
        data = json.loads(text)
        return Run(
            run_id=data["run_id"],
            definition=data["definition"],
            definition_hash=data["definition_hash"],
            current=data["current"],
            visits=dict(data["visits"]),
            history=list(data["history"]),
            status=data["status"],
        )
    except (ValueError, KeyError, TypeError) as e:
        raise FlowError(f"{path}: run file is corrupt ({e})") from e


def save_run(state_dir: Path, run: Run) -> None:
    """Write the run atomically (temp file + rename)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _run_path(state_dir, run.run_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": 1, **asdict(run)}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_run_id(state_dir: Path) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    while True:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
        run_id = f"{stamp}-{suffix}"
        if not _run_path(state_dir, run_id).exists():
            return run_id


def step_target(defn: Definition, visits: dict[str, int], current: str, label: str | None) -> str:
    """Return the state to enter next, applying max_visits / on_exceed."""
    st = defn.states[current]
    if st.end:
        raise FlowError(f"state '{current}' is an end state")
    if st.choices:
        labels = ", ".join(c.label for c in st.choices)
        if label is None:
            raise FlowError(f"a result is required; choose one of: {labels}")
        match = next((c for c in st.choices if c.label == label), None)
        if match is None:
            raise FlowError(f"unknown result '{label}'; choose one of: {labels}")
        target = match.goto
    else:
        if label is not None:
            raise FlowError(f"step '{current}' takes no --result")
        target = st.goto
    for _ in range(len(defn.states) + 1):
        t = defn.states[target]
        if t.max_visits is not None and visits.get(target, 0) >= t.max_visits:
            target = t.on_exceed
            continue
        return target
    raise FlowError("on_exceed chain does not terminate")


def start_run(defn_path: Path, state_dir: Path, cmd: str = "flow") -> str:
    """Create a run, save it, and return the first step's output."""
    defn = load_definition(defn_path)
    run = Run(
        run_id=_new_run_id(state_dir),
        definition=str(defn.path),
        definition_hash=_file_hash(defn.path),
        current=defn.start,
        visits={defn.start: 1},
        history=[],
        status="ended" if defn.states[defn.start].end else "running",
    )
    out = render_step(defn, run.current, run.run_id, cmd)
    save_run(state_dir, run)
    return out


def next_step(
    run_id: str, label: str | None, state_dir: Path, cmd: str = "flow", force: bool = False
) -> str:
    """Record the result of the current step and return the next step's output.

    Nothing is written unless every check passes.
    """
    run = load_run(state_dir, run_id)
    if run.status == "ended":
        raise FlowError(f"run already ended: {run_id}")
    path = Path(run.definition)
    if not path.is_file():
        raise FlowError(f"definition not found: {path}")
    new_hash = _file_hash(path)
    if new_hash != run.definition_hash and not force:
        raise FlowError(
            f"definition changed since the run started: {path} (use --force to continue anyway)"
        )
    defn = load_definition(path)
    if run.current not in defn.states:
        raise FlowError(f"current state '{run.current}' no longer exists in the definition")

    target = step_target(defn, run.visits, run.current, label)
    run.history.append(
        {
            "state": run.current,
            "label": label,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    )
    run.visits[target] = run.visits.get(target, 0) + 1
    run.current = target
    run.definition_hash = new_hash
    if defn.states[target].end:
        run.status = "ended"
    out = render_step(defn, target, run.run_id, cmd)
    save_run(state_dir, run)
    return out


def status_text(run_id: str, state_dir: Path) -> str:
    run = load_run(state_dir, run_id)
    visits = ", ".join(f"{k}={v}" for k, v in run.visits.items())
    lines = [
        f"Run: {run.run_id}",
        f"Definition: {run.definition}",
        f"Status: {run.status}",
        f"Current: {run.current}",
        f"Visits: {visits}",
    ]
    if run.history:
        lines.append("History:")
        lines += [
            f"  {i}. {h['state']} (result: {h['label'] or '-'})"
            for i, h in enumerate(run.history, 1)
        ]
    else:
        lines.append("History: (none)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# dry run
# ---------------------------------------------------------------------------

DRY_RUN_ID = "dry-run"
DRY_RUN_SEPARATOR = "\n---\n\n"
DRY_RUN_MAX_STEPS = 1000


def dry_run(defn_path: Path, results: list[str] | None, cmd: str = "flow") -> str:
    """Show what a run would print, without creating any state.

    Without results, every state is rendered in definition order. With results, the
    flow is walked from the start state; steps without choices advance on their own.
    """
    defn = load_definition(defn_path)
    if results is None:
        return DRY_RUN_SEPARATOR.join(
            render_step(defn, sid, DRY_RUN_ID, cmd) for sid in defn.states
        )

    queue = list(results)
    visits = {defn.start: 1}
    current = defn.start
    steps = [render_step(defn, current, DRY_RUN_ID, cmd)]
    note = ""
    for _ in range(DRY_RUN_MAX_STEPS):
        st = defn.states[current]
        if st.end:
            break
        if st.choices:
            if not queue:
                note = f"(results exhausted at {current})"
                break
            label = queue.pop(0)
        else:
            label = None
        current = step_target(defn, visits, current, label)
        visits[current] = visits.get(current, 0) + 1
        steps.append(render_step(defn, current, DRY_RUN_ID, cmd))
    else:
        raise FlowError(f"dry-run did not finish within {DRY_RUN_MAX_STEPS} steps")
    if queue:
        note = f"(results left over: {', '.join(queue)})"
    out = DRY_RUN_SEPARATOR.join(steps)
    return out + (f"\n{note}\n" if note else "")


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def _default_cmd() -> str:
    """The command prefix printed in 'next' hints; copy-pasteable as is."""
    return os.environ.get("FLOW_CMD") or f"uv run {Path(sys.argv[0]).absolute()}"


def _resolve_state_dir(arg: Path | None) -> Path:
    if arg is not None:
        return arg
    env = os.environ.get("FLOW_STATE_DIR")
    return Path(env) if env else Path.cwd() / ".flow" / "runs"


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--state-dir",
        type=Path,
        help="directory for run state files (default: $FLOW_STATE_DIR or ./.flow/runs)",
    )
    parser = argparse.ArgumentParser(prog="flow", description="Step-by-step flow runner.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("start", parents=[common], help="start a run and print the first step")
    p.add_argument("definition", type=Path)

    p = sub.add_parser("next", parents=[common], help="record a result and print the next step")
    p.add_argument("run_id")
    p.add_argument("--result", help="the chosen result label")
    p.add_argument("--force", action="store_true", help="continue even if the definition changed")

    p = sub.add_parser("status", parents=[common], help="show where a run is")
    p.add_argument("run_id")

    p = sub.add_parser("lint", help="check a definition")
    p.add_argument("definition", type=Path)

    p = sub.add_parser("dry-run", help="show the steps without creating a run")
    p.add_argument("definition", type=Path)
    p.add_argument("--results", help="comma-separated result labels to walk through")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "lint":
            issues = lint(args.definition)
            for issue in issues:
                print(format_issue(issue))
            return 1 if any(i.level == "error" for i in issues) else 0
        if args.command == "dry-run":
            results = None
            if args.results is not None:
                results = [r.strip() for r in args.results.split(",") if r.strip()]
            sys.stdout.write(dry_run(args.definition, results, _default_cmd()))
            return 0
        state_dir = _resolve_state_dir(args.state_dir)
        if args.command == "start":
            out = start_run(args.definition, state_dir, _default_cmd())
        elif args.command == "next":
            out = next_step(args.run_id, args.result, state_dir, _default_cmd(), args.force)
        else:
            out = status_text(args.run_id, state_dir)
        sys.stdout.write(out)
        return 0
    except FlowError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
