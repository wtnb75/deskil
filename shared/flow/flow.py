#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""flow: a deterministic state-machine runner for step-by-step skills.

Single file, standard library only (Python 3.11+).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import random
import re
import shlex
import signal
import string
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass, field
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


def read_source(path: Path) -> bytes:
    """Read a file's bytes, converting I/O errors into FlowError."""
    try:
        return path.read_bytes()
    except OSError as e:
        raise FlowError(f"{path}: cannot read file ({e.strerror})") from e


def parse_toml(path: Path, data: bytes) -> dict:
    """Parse TOML text read from `path`, converting encoding and syntax errors into FlowError."""
    try:
        return tomllib.loads(data.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise FlowError(f"{path}: not valid UTF-8 ({e.reason})") from e
    except tomllib.TOMLDecodeError as e:
        raise FlowError(f"{path}: {e}") from e


def read_toml(path: Path) -> dict:
    """Parse a TOML file, converting I/O and syntax errors into FlowError."""
    return parse_toml(path, read_source(path))


# ---------------------------------------------------------------------------
# linter: schema checks
# ---------------------------------------------------------------------------

ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LABEL_RE = re.compile(r"^[A-Za-z0-9_]+$")

TOP_KEYS = {"schema", "start", "notes", "states"}
NOTES_KEYS = {"always", "common"}
STATE_KEYS = {
    "prompt", "notes", "goto", "choices", "end", "max_visits", "on_exceed", "delegate",
    "run", "timeout", "cwd", "output_lines", "include", "exits",
}
# An include state is replaced by the states of another definition; it takes only these keys.
INCLUDE_KEYS = ("include", "exits")
# Joins a state id and an included state id in the expanded definition (`<state>__<sub state>`).
INCLUDE_SEP = "__"
# Options that only make sense together with `run`.
RUN_OPTION_KEYS = ("timeout", "cwd", "output_lines")
DEFAULT_TIMEOUT = 300
DEFAULT_OUTPUT_LINES = 100
DEFAULT_REF = "main"
# The only variable flow expands in a `run` argument: the directory of the definition file.
DEF_DIR_VAR = "${DEF_DIR}"
VARIABLE_RE = re.compile(r"\$\{[^}]*\}")
CHOICE_KEYS = {"label", "when", "goto"}
# Subagent type names, optionally namespaced by a plugin (e.g. "reviewer", "plugin:agent").
AGENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]*$")


def _err(issues: list[Issue], code: str, where: str, message: str) -> None:
    issues.append(Issue("error", code, where, message))


def expand_argv(argv: list[str], base_dir: Path) -> list[str]:
    """Replace ${DEF_DIR} in each argument with the definition's directory; nothing else changes."""
    return [a.replace(DEF_DIR_VAR, str(base_dir)) for a in argv]


def _check_keys(obj: dict, allowed: set[str], where: str, issues: list[Issue]) -> None:
    for key in obj:
        if key not in allowed:
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
    try:
        target = (base / rel).resolve()
        outside = rel.is_absolute() or not target.is_relative_to(base)
        is_file = not outside and target.is_file()
    except ValueError:  # e.g. an embedded NUL character
        _err(issues, "file-missing", where, f"invalid file path: {value['file']!r}")
        return
    if outside:
        _err(issues, "file-outside", where, f"'{value['file']}' is outside the definition directory")
    elif not is_file:
        _err(issues, "file-missing", where, f"file not found: {value['file']}")


def _check_target(value: object, where: str, state_ids: set[str], issues: list[Issue]) -> None:
    """A transition target must be the id of an existing state."""
    if isinstance(value, str):
        if value not in state_ids:
            _err(issues, "missing-target", where, f"target state not found: {value!r}")
    elif value is None:
        _err(issues, "missing-target", where, "target state is missing")
    else:
        _err(issues, "type", where, "target must be a state id (a string)")


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
        _check_target(ch.get("goto"), f"{cw}.goto", state_ids, issues)


def _check_run(st: dict, where: str, issues: list[Issue]) -> None:
    """Check `run` (a command as an argument list) and its options."""
    if "run" in st:
        argv = st["run"]
        if not (
            isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv)
        ):
            _err(issues, "type", f"{where}.run", "run must be a non-empty list of non-empty strings")
        else:
            for a in argv:
                for var in VARIABLE_RE.findall(a):
                    if var != DEF_DIR_VAR:
                        issues.append(Issue(
                            "warning", "unknown-variable", f"{where}.run",
                            f"'{var}' is not expanded (only {DEF_DIR_VAR} is) and is passed as is",
                        ))
    else:
        for key in RUN_OPTION_KEYS:
            if key in st:
                _err(issues, "option-without-run", f"{where}.{key}", f"{key} has no effect without run")
    for key in ("timeout", "output_lines"):
        if key in st and (type(st[key]) is not int or st[key] < 1):
            _err(issues, "type", f"{where}.{key}", f"{key} must be an integer >= 1")
    if "cwd" in st:
        cwd = st["cwd"]
        if not isinstance(cwd, str) or not cwd:
            _err(issues, "type", f"{where}.cwd", "cwd must be a relative path (a string)")
        elif Path(cwd).is_absolute() or ".." in Path(cwd).parts:
            _err(issues, "cwd-outside", f"{where}.cwd", f"'{cwd}' must stay inside the definition directory")


def _check_include(st: dict, where: str, state_ids: set[str], issues: list[Issue]) -> None:
    """Check an include state: only `include` (a path) and `exits` (end state id -> state id)."""
    for key in st:
        if key in STATE_KEYS and key not in INCLUDE_KEYS:
            _err(issues, "include-with-other-keys", f"{where}.{key}", f"'{key}' cannot be used with include")
    if not isinstance(st["include"], str) or not st["include"]:
        _err(issues, "type", f"{where}.include", "include must be a path (a string)")
    exits = st.get("exits", {})
    if not isinstance(exits, dict):
        _err(issues, "type", f"{where}.exits", "exits must be a table of end state id = state id")
        return
    for end_id, target in exits.items():
        _check_target(target, f"{where}.exits.{end_id}", state_ids, issues)


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
    if "include" in st:
        _check_include(st, where, state_ids, issues)
        return
    if "exits" in st:
        _err(issues, "exits-without-include", f"{where}.exits", "exits has no effect without include")

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
    if is_end and any(
        k in st for k in ("goto", "choices", "max_visits", "on_exceed", "delegate", "run")
    ):
        _err(
            issues,
            "end-with-transition",
            where,
            "an end state cannot have goto/choices/max_visits/on_exceed/delegate/run",
        )
    else:
        count = sum(1 for k in ("goto", "choices") if k in st) + (1 if is_end else 0)
        if count != 1:
            _err(issues, "transition-count", where, "exactly one of goto / choices / end is required")

    if "delegate" in st:
        agent = st["delegate"]
        if not isinstance(agent, str) or not AGENT_RE.match(agent):
            _err(
                issues,
                "type",
                f"{where}.delegate",
                f"delegate must be an agent name matching {AGENT_RE.pattern}",
            )

    _check_run(st, where, issues)

    if "goto" in st:
        _check_target(st["goto"], f"{where}.goto", state_ids, issues)
    if "choices" in st:
        _check_choices(st["choices"], where, state_ids, base_dir, issues)

    mv = st.get("max_visits")
    if "max_visits" in st and (type(mv) is not int or mv < 1):
        _err(issues, "type", f"{where}.max_visits", "max_visits must be an integer >= 1")
    if "max_visits" in st and "on_exceed" not in st and not is_end:
        _err(issues, "on-exceed-missing", where, "max_visits requires on_exceed")
    if "on_exceed" in st:
        _check_target(st["on_exceed"], f"{where}.on_exceed", state_ids, issues)
        if "max_visits" not in st and not is_end:
            _err(issues, "on-exceed-without-max-visits", where, "on_exceed has no effect without max_visits")


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

    # A cycle made only of on_exceed edges cannot terminate once every member is over its limit.
    exceed_graph = {
        sid: [states[sid]["on_exceed"]] if sid in reachable and "on_exceed" in states[sid] else []
        for sid in states
    }
    for comp in _sccs(exceed_graph):
        if len(comp) > 1 or comp[0] in exceed_graph[comp[0]]:
            members = ", ".join(sorted(comp))
            issues.append(
                Issue(
                    "error",
                    "on-exceed-cycle",
                    f"states.{sorted(comp)[0]}",
                    f"on_exceed chain loops forever once the limits are reached ({members})",
                )
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


# ---------------------------------------------------------------------------
# include: expanding parts into one state machine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Exit:
    """An edge into an end state of an included definition, to be replaced by its `exits` target."""

    end_id: str


def _rewrite_text(value: Text, reldir: str) -> Text:
    """Make a { file = ... } path relative to the root definition's directory."""
    if reldir == "." or isinstance(value, str):
        return value
    return {"file": posixpath.normpath(posixpath.join(reldir, value["file"]))}


def _localize(st: dict, reldir: str, prefix: str) -> dict:
    """Copy a state of an included definition, rewriting what depends on where the part lives."""
    out = dict(st)
    if prefix and "notes" in out:
        out["notes"] = [prefix + n for n in out["notes"]]
    if reldir == ".":
        return out
    if "prompt" in out:
        out["prompt"] = _rewrite_text(out["prompt"], reldir)
    if "choices" in out:
        out["choices"] = [{**c, "when": _rewrite_text(c["when"], reldir)} for c in out["choices"]]
    if "run" in out:  # ${DEF_DIR} is the directory of the part that wrote the command
        out["run"] = [a.replace(DEF_DIR_VAR, f"{DEF_DIR_VAR}/{reldir}") for a in out["run"]]
    if "cwd" in out:
        out["cwd"] = posixpath.normpath(posixpath.join(reldir, out["cwd"]))
    return out


def _map_edges(st: dict, fn) -> dict:
    """Copy a state with every transition target (goto, choices, on_exceed) passed through fn."""
    out = dict(st)
    if "goto" in out:
        out["goto"] = fn(out["goto"])
    if "on_exceed" in out:
        out["on_exceed"] = fn(out["on_exceed"])
    if "choices" in out:
        out["choices"] = [{**c, "goto": fn(c["goto"])} for c in out["choices"]]
    return out


def _expand_include(
    sid: str, st: dict, base: Path, reldir: str, prefix: str, stack: list[Path], read,
    issues: list[Issue], label: str,
) -> tuple[dict, dict, str] | None:
    """Load and expand the part named by an include state: (states, common notes, entry state).

    Returns None after reporting why the part cannot be used. `stack` holds the resolved paths
    of the definitions being expanded (the ancestors), so a part may be included twice but never
    inside itself.
    """
    where = f"{label}states.{sid}"
    rel = st["include"]
    norm = posixpath.normpath(rel)
    if os.path.isabs(rel) or norm == ".." or norm.startswith("../"):
        _err(issues, "include-outside", f"{where}.include", f"'{rel}' is outside the definition directory")
        return None
    # The path is judged as written (not after following symlinks): a symlink is how a part
    # is shared between definitions.
    target = base / norm
    try:
        real = target.resolve()
        is_file = target.is_file()
    except (OSError, ValueError, RuntimeError):
        real, is_file = target, False
    if not is_file:
        _err(issues, "include-missing", f"{where}.include", f"file not found: {rel}")
        return None
    if real in stack:
        _err(issues, "include-cycle", f"{where}.include", f"'{rel}' includes itself (directly or not)")
        return None
    try:
        sub_raw = read(target)
    except FlowError as e:
        _err(issues, "include-unreadable", f"{where}.include", str(e))
        return None
    sub_label = f"{label}{norm}: "
    sub_issues = [Issue(i.level, i.code, sub_label + i.where, i.message) for i in lint_schema(sub_raw, target.parent)]
    issues.extend(sub_issues)
    if any(i.level == "error" for i in sub_issues):
        return None
    sub_reldir = posixpath.normpath(posixpath.join(reldir, posixpath.dirname(norm) or "."))
    states, common, start, ends = _expand_level(
        sub_raw, target.parent, sub_reldir, prefix, True, [*stack, real], read, issues, sub_label
    )
    if isinstance(start, _Exit):
        _err(issues, "include-start-end", where, f"'{rel}' starts at an end state")
        return None
    exits = st.get("exits", {})
    missing, unknown = sorted(ends - set(exits)), sorted(set(exits) - ends)
    for end_id in missing:
        _err(issues, "exits-missing", f"{where}.exits", f"no exit for the end state '{end_id}' of {rel}")
    for end_id in unknown:
        _err(issues, "exits-unknown", f"{where}.exits.{end_id}", f"'{end_id}' is not an end state of {rel}")
    if missing or unknown:
        return None
    return states, common, start


def _expand_level(
    raw: dict, base: Path, reldir: str, prefix: str, is_sub: bool, stack: list[Path], read,
    issues: list[Issue], label: str,
) -> tuple[dict, dict, str | _Exit, set[str]]:
    """Expand the include states of one (already schema-checked) definition.

    Returns (states, common notes, entry state, end state ids). In a part (`is_sub`), end states
    are dropped and edges into them become _Exit; the includer replaces those with its `exits`.
    """
    src = raw["states"]
    notes = raw.get("notes", {})
    always = [_rewrite_text(a, reldir) for a in notes.get("always", [])]
    common = {prefix + n: _rewrite_text(v, reldir) for n, v in notes.get("common", {}).items()}
    out: dict[str, dict] = {}
    entries: dict[str, str] = {}  # include state id -> entry state of its part
    parts: dict[str, tuple[dict, dict]] = {}  # include state id -> (its part's states, exits)
    for sid, st in src.items():
        if "include" not in st:
            continue
        res = _expand_include(
            sid, st, base, reldir, f"{prefix}{sid}{INCLUDE_SEP}", stack, read, issues, label
        )
        if res is None:
            entries[sid] = prefix + sid  # the error is already reported
            continue
        sub_states, sub_common, sub_start = res
        entries[sid] = sub_start
        parts[sid] = (sub_states, st.get("exits", {}))
        for name, item in sub_common.items():
            if name in common:
                _err(issues, "id-collision", f"{label}notes.common.{name}", f"note name '{name}' is defined twice")
            common[name] = item

    def local(target: str) -> str | _Exit:
        if target in entries:
            return entries[target]
        if is_sub and src[target].get("end") is True:
            return _Exit(target)
        return prefix + target

    def add(new_id: str, st: dict) -> None:
        if new_id in out:
            _err(issues, "id-collision", f"{label}states.{new_id}", f"state id '{new_id}' is defined twice")
        out[new_id] = st

    for sid, st in src.items():  # in definition order; a part's states take its include's place
        if sid in parts:
            sub_states, exits = parts[sid]

            def through_exits(target, exits=exits):
                return local(exits[target.end_id]) if isinstance(target, _Exit) else target

            for sub_id, sub_st in sub_states.items():
                add(sub_id, _map_edges(sub_st, through_exits))
        elif "include" not in st and not (is_sub and st.get("end") is True):
            new = _map_edges(_localize(st, reldir, prefix), local)
            new["_always"] = always
            add(prefix + sid, new)
    ends = {sid for sid, st in src.items() if st.get("end") is True}
    return out, common, local(raw["start"]), ends


def expand_includes(raw: dict, path: Path, read=read_toml) -> tuple[dict, list[Issue]]:
    """Expand include states into one definition; return it with the problems found.

    `raw` is the parsed root definition at `path` and has passed lint_schema. `read(path)`
    returns the parsed TOML of a part. The result has no include states; every state has `_always`
    (the `notes.always` of the definition that wrote it) and part states are named
    `<include state>__<state>`.
    """
    issues: list[Issue] = []
    root = path.resolve()
    states, common, start, _ = _expand_level(raw, root.parent, ".", "", False, [root], read, issues, "")
    return {"schema": 1, "start": start, "notes": {"common": common}, "states": states}, issues


def lint(path: Path) -> list[Issue]:
    """Lint a definition file. Graph checks run only if the schema is clean."""
    return lint_raw(read_toml(path), path)


def lint_raw(raw: dict, path: Path, read=read_toml) -> list[Issue]:
    """Lint an already parsed definition that was read from `path`."""
    return _lint_expanded(raw, path, read)[0]


def _lint_expanded(raw: dict, path: Path, read) -> tuple[list[Issue], dict | None]:
    """Lint a definition and its parts; also return the expanded definition if it is free of errors."""
    issues = lint_schema(raw, path.resolve().parent)
    if any(i.level == "error" for i in issues):
        return issues, None
    merged, more = expand_includes(raw, path, read)
    issues += more
    if any(i.level == "error" for i in issues):
        return issues, None
    issues += lint_graph(merged)
    return issues, merged


def format_issue(issue: Issue) -> str:
    return f"{issue.level}[{issue.code}] {issue.where}: {issue.message}"


LINT_FORMATS = ("text", "json", "github")


def _gh_data(text: str) -> str:
    """Escape the message of a GitHub Actions workflow command."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _gh_property(text: str) -> str:
    """Escape a property value (such as file=) of a GitHub Actions workflow command."""
    return _gh_data(text).replace(":", "%3A").replace(",", "%2C")


def format_lint(path: Path, issues: list[Issue], fmt: str) -> str:
    """Render lint results. Issues carry no line numbers, so `github` points at the file only."""
    if fmt == "json":
        data = {"file": str(path), "issues": [asdict(i) for i in issues]}
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if fmt == "github":
        return "".join(
            f"::{i.level} file={_gh_property(str(path))}::"
            f"{_gh_data(f'[{i.code}] {i.where}: {i.message}')}\n"
            for i in issues
        )
    return "".join(format_issue(i) + "\n" for i in issues)


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
    delegate: str | None = None
    run: tuple[str, ...] | None = None
    timeout: int | None = None
    cwd: str | None = None
    output_lines: int | None = None
    always: tuple[Text, ...] = ()  # notes.always of the definition that wrote this state


@dataclass(frozen=True)
class Definition:
    path: Path
    base_dir: Path
    start: str
    always: tuple[Text, ...]  # notes.always of the root definition
    common: dict[str, Text]
    states: dict[str, State]
    sources: dict[Path, bytes] = field(default_factory=dict)  # every file read, with its bytes
    hash: str = ""  # identifies the exact text of all the files


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


def _definition_hash(path: Path, sources: dict[Path, bytes]) -> str:
    """sha256 of the root file; with includes, of the root and every part (names included)."""
    h = hashlib.sha256(sources[path])
    for part in sorted(p for p in sources if p != path):
        h.update(b"\0" + part.relative_to(path.parent).as_posix().encode() + b"\0" + sources[part])
    return h.hexdigest()


def load_definition(path: Path) -> Definition:
    """Lint a definition (and its parts) and build it. Any lint error raises FlowError."""
    path = Path(path).resolve()
    sources: dict[Path, bytes] = {}

    def read(p: Path) -> dict:
        # Each file is read once: the lint, the build and the hash must see the same text.
        if p not in sources:
            sources[p] = read_source(p)
        return parse_toml(p, sources[p])

    raw = read(path)
    issues, merged = _lint_expanded(raw, path, read)
    errors = [i for i in issues if i.level == "error"]
    if errors or merged is None:
        lines = "\n".join(format_issue(i) for i in errors)
        raise FlowError(f"{path}: definition has errors\n{lines}")
    states = {}
    for sid, st in merged["states"].items():
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
            delegate=st.get("delegate"),
            run=tuple(st["run"]) if "run" in st else None,
            timeout=st.get("timeout"),
            cwd=st.get("cwd"),
            output_lines=st.get("output_lines"),
            always=tuple(st["_always"]),
        )
    return Definition(
        path=path,
        base_dir=path.parent,
        start=merged["start"],
        always=tuple(raw.get("notes", {}).get("always", [])),
        common=dict(merged["notes"]["common"]),
        states=states,
        sources=sources,
        hash=_definition_hash(path, sources),
    )


# ---------------------------------------------------------------------------
# rendering a step for the LLM
# ---------------------------------------------------------------------------


def render_command(result: dict) -> str:
    """Render the command section of a step: the outcome, or why nothing was run."""
    shown = shlex.join(result["argv"])
    if not result["executed"]:
        return f"Command not executed ({result['reason']}): `{shown}`"
    lines = [f"Command: `{shown}`"]
    if result.get("error"):
        lines.append(f"Failed to start: {result['error']}")
        return "\n".join(lines)
    if result["exit_code"] is None:
        lines.append(f"Exit code: timeout (killed after {result['timeout']}s)")
    else:
        lines.append(f"Exit code: {result['exit_code']}")
    for name in ("stdout", "stderr"):
        text = result[name]
        cut = result[f"{name}_truncated"]
        if not text and not cut:
            lines.append(f"{name}: (empty)")
            continue
        head = f"{name} (last {result['output_lines']} lines"
        if cut:
            head += f"; {cut} lines truncated; full output: {result[f'{name}_file']}"
        lines.append(head + "):")
        lines.append(text.rstrip("\n"))
    return "\n".join(lines)


def render_step(
    defn: Definition, state_id: str, run_id: str, cmd: str = "flow", command: dict | None = None
) -> str:
    """Render what the LLM sees for one state. Reads only the files that state needs.

    `command` is the outcome of the state's `run` (see execute_state), if there is one.
    """
    st = defn.states[state_id]
    sections = [f"[{st.id}] (run: {run_id})\n{read_text_value(st.prompt, defn.base_dir)}"]

    notes: list[str] = []
    for item in [*st.always, *(defn.common[n] for n in st.notes)]:
        text = read_text_value(item, defn.base_dir)
        if text not in notes:
            notes.append(text)
    if notes:
        sections.append("Notes:\n" + "\n".join(f"- {n}" for n in notes))

    if command is not None:
        sections.append(render_command(command))

    if st.delegate:
        sections.append(
            f"Delegate: hand this step to the subagent `{st.delegate}` "
            f"(Agent tool, subagent_type = {st.delegate}). Give it this whole step text. "
            "It does the work, runs the command shown below, "
            "and returns that command's output to you. Continue from that output."
        )

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
    ref: str = DEFAULT_REF  # commands run only if the definition equals this git ref's copy
    cwd: str = ""  # where `start` ran; the default working directory of commands
    commands: list[dict] = field(default_factory=list)  # one record per command step entered


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
            ref=data.get("ref", DEFAULT_REF),
            cwd=data.get("cwd", ""),
            commands=list(data.get("commands", [])),
        )
    except (ValueError, KeyError, TypeError) as e:
        raise FlowError(f"{path}: run file is corrupt ({e})") from e


def save_run(state_dir: Path, run: Run) -> None:
    """Write the run atomically (temp file + rename)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _run_path(state_dir, run.run_id)
    fd, tmp_name = tempfile.mkstemp(dir=state_dir, prefix=f"{run.run_id}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"schema": 1, **asdict(run)}, indent=2) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _new_run_id(state_dir: Path) -> str:
    """Pick an unused run id and reserve it by creating its (empty) run file."""
    state_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    while True:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
        run_id = f"{stamp}-{suffix}"
        try:
            os.close(os.open(_run_path(state_dir, run_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except FileExistsError:
            continue
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


def _tail(data: bytes, limit: int) -> tuple[str, int]:
    """Decode output and keep its last `limit` lines; return (text, number of lines cut)."""
    lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
    cut = max(0, len(lines) - limit)
    return "".join(lines[cut:]), cut


def _git(directory: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )


def _git_fail(proc: subprocess.CompletedProcess) -> str:
    detail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()
    return detail[-1] if detail else "git failed"


def _check_links(source: Path, base: Path, ref: str) -> str | None:
    """Return why a symlink on the way from `base` to `source` is not the committed one.

    Each link component must be a symlink at `ref` with the same target as in the working
    tree; otherwise the link could be re-pointed at another committed file to pass the
    content comparison.
    """
    current = base
    for part in source.relative_to(base).parts:
        current = current / part
        if not current.is_symlink():
            continue
        parent = current.parent.resolve()
        try:
            tree = _git(parent, "ls-tree", ref, "--", current.name)
            blob = _git(parent, "show", f"{ref}:./{current.name}")
        except (OSError, subprocess.SubprocessError) as e:
            return f"cannot run git: {e}"
        mode = tree.stdout.decode("utf-8", errors="replace").split(" ", 1)[0]
        if tree.returncode != 0 or blob.returncode != 0 or mode != "120000":
            return f"the link '{current.relative_to(base).as_posix()}' is not a symlink at ref '{ref}'"
        if blob.stdout != os.readlink(current).encode():
            return f"the link '{current.relative_to(base).as_posix()}' differs from ref '{ref}'"
    return None


def _toplevel(directory: Path) -> str | None:
    proc = _git(directory, "rev-parse", "--show-toplevel")
    return proc.stdout.decode("utf-8", errors="replace").strip() if proc.returncode == 0 else None


def _ref_check(defn: Definition, ref: str) -> str | None:
    """Return why the commands must not run, or None if every file equals its copy at `ref`.

    Every file the definition was built from (the root and all parts) is compared with the
    committed bytes, so what runs is what git holds. A part reached through a symlink is
    looked up at its real path, which must be in the same repository as the root definition,
    and each symlink on the way must be the committed one.
    """
    try:
        root_top = _toplevel(defn.base_dir)
        for source, data in defn.sources.items():
            real = source.resolve()
            if source != defn.path:
                if _toplevel(real.parent) != root_top:
                    rel = source.relative_to(defn.base_dir).as_posix()
                    return f"the included file '{rel}' is not in the definition's repository"
                reason = _check_links(source, defn.base_dir, ref)
                if reason:
                    return reason
            proc = _git(real.parent, "show", f"{ref}:./{real.name}")
            if proc.returncode != 0:
                return f"cannot read {real.name} at ref '{ref}': {_git_fail(proc)}"
            if proc.stdout != data:
                name = "the definition" if source == defn.path else (
                    f"the included file '{source.relative_to(defn.base_dir).as_posix()}'"
                )
                return f"{name} differs from ref '{ref}'"
    except (OSError, subprocess.SubprocessError) as e:
        return f"cannot run git: {e}"
    return None


def execute_state(
    defn: Definition, st: State, run: Run, state_dir: Path | None, dry: bool = False
) -> dict | None:
    """Run the command of a state (if it has one) and return its record.

    The command runs only if every file of the definition (the root and its parts) is identical
    to its copy at the run's ref (checked on every call, so editing a file and using --force
    cannot smuggle in commands). The definition was built from the bytes that were compared.
    Otherwise the command is only shown. A command that cannot start is reported, not raised.
    """
    if st.run is None:
        return None
    visit = run.visits.get(st.id, 1)
    limit = st.output_lines or DEFAULT_OUTPUT_LINES
    timeout = st.timeout or DEFAULT_TIMEOUT
    rec: dict = {
        "state": st.id, "visit": visit, "argv": expand_argv(list(st.run), defn.base_dir),
        "executed": False,
        "reason": "", "output_lines": limit, "timeout": timeout, "error": None,
        "exit_code": None, "stdout": "", "stderr": "", "stdout_truncated": 0,
        "stderr_truncated": 0, "stdout_file": None, "stderr_file": None,
    }
    reason = "dry run" if dry else _ref_check(defn, run.ref)
    if reason:
        rec["reason"] = reason
        return rec
    rec["executed"] = True
    argv = rec["argv"]
    cwd = defn.base_dir / st.cwd if st.cwd else Path(run.cwd or Path.cwd())
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as e:
        rec["error"] = f"{e.strerror or e} ({argv[0]})"
        return rec
    try:
        out, err = proc.communicate(timeout=timeout)
        rec["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the whole group, so grandchildren die too
        except OSError:
            proc.kill()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    for name, data in (("stdout", out), ("stderr", err)):
        rec[name], rec[f"{name}_truncated"] = _tail(data, limit)
        if state_dir is not None:
            target = state_dir / run.run_id / f"{st.id}-{visit}.{name}"
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                rec[f"{name}_file"] = str(target)
            except OSError:
                pass  # the full text is best effort; the tail is still reported
    return rec


def _enter(defn: Definition, run: Run, state_dir: Path, cmd: str) -> str:
    """Run the current state's command (if any), record it, and render the step."""
    result = execute_state(defn, defn.states[run.current], run, state_dir)
    if result is not None:
        run.commands.append(result)
    return render_step(defn, run.current, run.run_id, cmd, result)


def start_run(
    defn_path: Path, state_dir: Path, cmd: str = "flow", ref: str = DEFAULT_REF
) -> str:
    """Create a run, save it, and return the first step's output."""
    defn = load_definition(defn_path)
    run = Run(
        run_id=_new_run_id(state_dir),
        definition=str(defn.path),
        definition_hash="",
        current=defn.start,
        visits={defn.start: 1},
        history=[],
        status="ended" if defn.states[defn.start].end else "running",
        ref=ref,
        cwd=str(Path.cwd()),
    )
    try:
        run.definition_hash = defn.hash
        out = _enter(defn, run, state_dir, cmd)
        save_run(state_dir, run)
    except BaseException:
        _run_path(state_dir, run.run_id).unlink(missing_ok=True)  # release the reserved id
        raise
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
    defn = load_definition(path)
    new_hash = defn.hash
    if new_hash != run.definition_hash and not force:
        raise FlowError(
            f"definition changed since the run started: {path} (use --force to continue anyway)"
        )
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
    out = _enter(defn, run, state_dir, cmd)
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


def _dry_step(defn: Definition, state_id: str, cmd: str) -> str:
    """Render one step for a dry run: a state's command is shown, never executed."""
    run = Run(DRY_RUN_ID, str(defn.path), "", state_id, {}, [], "running")
    result = execute_state(defn, defn.states[state_id], run, None, dry=True)
    return render_step(defn, state_id, DRY_RUN_ID, cmd, result)


def dry_run(defn_path: Path, results: list[str] | None, cmd: str = "flow") -> str:
    """Show what a run would print, without creating any state.

    Without results, every state is rendered in definition order. With results, the
    flow is walked from the start state; steps without choices advance on their own.
    """
    defn = load_definition(defn_path)
    if results is None:
        return DRY_RUN_SEPARATOR.join(
            _dry_step(defn, sid, cmd) for sid in defn.states
        )

    queue = list(results)
    visits = {defn.start: 1}
    current = defn.start
    steps = [_dry_step(defn, current, cmd)]
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
        steps.append(_dry_step(defn, current, cmd))
    else:
        raise FlowError(f"dry-run did not finish within {DRY_RUN_MAX_STEPS} steps")
    if queue:
        note = f"(results left over: {', '.join(queue)})"
    out = DRY_RUN_SEPARATOR.join(steps)
    return out + (f"\n{note}\n" if note else "")


# ---------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------


def graph_mermaid(defn_path: Path) -> str:
    """Draw the state transitions of a definition as a Mermaid flowchart.

    Node ids are prefixed with `n_` so a state named like a Mermaid keyword (`end`) is safe.
    A goto or a choice is a solid arrow (a choice carries its label); on_exceed is dashed.
    """
    defn = load_definition(defn_path)
    lines = ["flowchart TD", f"  start_node((start)) --> n_{defn.start}"]
    for st in defn.states.values():
        shape = f'(["{st.id}"])' if st.end else f'["{st.id}"]'
        lines.append(f"  n_{st.id}{shape}")
    for st in defn.states.values():
        if st.goto is not None:
            lines.append(f"  n_{st.id} --> n_{st.goto}")
        for c in st.choices:
            lines.append(f"  n_{st.id} -->|{c.label}| n_{c.goto}")
        if st.on_exceed is not None:
            lines.append(f"  n_{st.id} -.->|max {st.max_visits}| n_{st.on_exceed}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def _split_comment(line: str) -> tuple[str, str]:
    """Split a TOML line into (code, trailing comment); a # inside a string is not a comment."""
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i], line[i:]
        i += 1
    return line, ""


def _rewrite_ids(text: str, old: str, new: str) -> str:
    """Rename a state id in table headers and in start/goto/on_exceed values.

    Comments and multi-line strings (prompt bodies) are left untouched.
    """
    old_re = re.escape(old)
    # Accept `[states.b]`, `[states . b]` and `[states."b"]` (the quotes are kept).
    head_re = re.compile(rf"""^(\s*\[\[?\s*states\s*\.\s*)(["']?){old_re}\2(?=[.\]\s])""")
    # A key must start the line, or follow `{` / `,` inside an inline table.
    key_re = re.compile(rf"""(?:^|(?<=[{{,]))(\s*)(start|goto|on_exceed)(\s*=\s*)(["']){old_re}\4""")
    out: list[str] = []
    delim: str | None = None  # open multi-line string delimiter, if inside one
    for line in text.splitlines(keepends=True):
        if delim is not None:
            if delim in line:
                delim = None
            out.append(line)
            continue
        if not line.lstrip().startswith("#"):
            code, comment = _split_comment(line)
            code = head_re.sub(lambda m: f"{m.group(1)}{m.group(2)}{new}{m.group(2)}", code)
            code = key_re.sub(
                lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{new}{m.group(4)}", code
            )
            line = code + comment
            for d in ('"""', "'''"):
                if line.count(d) % 2 == 1:
                    delim = d
                    break
        out.append(line)
    return "".join(out)


def rename_state(defn_path: Path, old: str, new: str) -> None:
    """Rename a state everywhere it is referenced.

    The result is linted before it replaces the file; if it introduces any new
    lint error, the original file is left untouched and FlowError is raised.
    """
    path = Path(defn_path)
    states = read_toml(path).get("states")
    if not isinstance(states, dict) or old not in states:
        raise FlowError(f"state not found: {old}")
    if not ID_RE.match(new):
        raise FlowError(f"invalid state id '{new}': must match {ID_RE.pattern}")
    if new in states:
        raise FlowError(f"state already exists: {new}")

    def errors_of(p: Path) -> Counter:
        return Counter(i.code for i in lint(p) if i.level == "error")

    before = errors_of(path)
    new_text = _rewrite_ids(path.read_bytes().decode("utf-8"), old, new)
    try:
        renamed = tomllib.loads(new_text).get("states")
    except tomllib.TOMLDecodeError:
        renamed = {new: None}  # a syntax error is reported by the lint below
    if not isinstance(renamed, dict) or new not in renamed:
        raise FlowError(
            f"cannot find the table header of state '{old}' in a supported form "
            f"([states.{old}]); {path} was not changed"
        )
    tmp =path.with_name(path.name + ".rename.tmp")
    tmp.write_bytes(new_text.encode("utf-8"))
    try:
        after = errors_of(tmp)
        worse = sorted(code for code, n in after.items() if n > before.get(code, 0))
        if worse:
            raise FlowError(
                f"rename would introduce lint errors ({', '.join(worse)}); {path} was not changed"
            )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


def _default_cmd() -> str:
    """The command prefix printed in 'next' hints; copy-pasteable as is."""
    return os.environ.get("FLOW_CMD") or f"uv run {shlex.quote(str(Path(sys.argv[0]).absolute()))}"


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
    p.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"git ref whose copy of the definition may run its commands (default: {DEFAULT_REF}); "
        "a definition that differs from it is shown only",
    )

    p = sub.add_parser("next", parents=[common], help="record a result and print the next step")
    p.add_argument("run_id")
    p.add_argument("--result", help="the chosen result label")
    p.add_argument("--force", action="store_true", help="continue even if the definition changed")

    p = sub.add_parser("status", parents=[common], help="show where a run is")
    p.add_argument("run_id")

    p = sub.add_parser("lint", help="check a definition")
    p.add_argument("definition", type=Path)
    p.add_argument(
        "--format",
        choices=LINT_FORMATS,
        default="text",
        help="output format: text (default), json, or github (Actions workflow commands)",
    )

    p = sub.add_parser("dry-run", help="show the steps without creating a run")
    p.add_argument("definition", type=Path)
    p.add_argument("--results", help="comma-separated result labels to walk through")

    p = sub.add_parser("graph", help="print the state transitions as a Mermaid flowchart")
    p.add_argument("definition", type=Path)

    p = sub.add_parser("rename", help="rename a state and all references to it")
    p.add_argument("definition", type=Path)
    p.add_argument("old")
    p.add_argument("new")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "lint":
            try:
                issues = lint(args.definition)
            except FlowError as e:
                if args.format == "text":
                    raise
                issues = [Issue("error", "read-error", "(file)", str(e))]
            sys.stdout.write(format_lint(args.definition, issues, args.format))
            return 1 if any(i.level == "error" for i in issues) else 0
        if args.command == "graph":
            sys.stdout.write(graph_mermaid(args.definition))
            return 0
        if args.command == "rename":
            rename_state(args.definition, args.old, args.new)
            print(f"renamed {args.old} -> {args.new}")
            return 0
        if args.command == "dry-run":
            results = None
            if args.results is not None:
                results = [r.strip() for r in args.results.split(",") if r.strip()]
            sys.stdout.write(dry_run(args.definition, results, _default_cmd()))
            return 0
        state_dir = _resolve_state_dir(args.state_dir)
        if args.command == "start":
            out = start_run(args.definition, state_dir, _default_cmd(), args.ref)
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
