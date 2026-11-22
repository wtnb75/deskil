#!/usr/bin/env python3
"""flow: a deterministic state-machine runner for step-by-step skills.

Single file, standard library only (Python 3.11+).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
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
