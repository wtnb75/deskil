---
name: flow-convert
description: Convert an existing skill into a skill driven by a deskil flow definition, with a correspondence table for the user to confirm
allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)
---

Convert an existing skill (`SKILL.md`) into a skill that runs on a deskil flow
definition. Every command below is run exactly as written. Writing the
definition itself follows `flow-author`.

## 1. Read the skill and classify every part

Read the whole `SKILL.md` (and any files it references). Sort each part into
one of two groups:

| Moves to `flow.toml` | Stays in `SKILL.md` |
|---|---|
| ordered steps | purpose and when to use the skill |
| branches ("if X, do Y") | context and domain knowledge |
| loops and their limits (retry at most N times) | background the steps rely on, glossary, examples |
| notes that apply to the whole procedure or to some steps | |

Rule of thumb: if the text says what to do next, or when to stop, it belongs
in the flow. If it explains what something is or why, it stays in `SKILL.md`.
A step that needs a lot of explanation keeps a short prompt in the flow, and
the explanation stays in `SKILL.md` or moves to a file referenced by
`prompt = { file = "..." }`.

A loop with no stated limit gets a `max_visits` and an `on_exceed` target.
Pick a limit that matches the original intent, and tell the user it was added.

## 2. Write the definition

Create `flow.toml` next to the skill, following `flow-author`: one state per
step, one `[[choices]]` block per outcome of each decision, `end = true` on the
final state. Do not change what a step does; only restructure it.

## 3. Check it

1. `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py lint <flow.toml>`: fix every error and read every warning.
2. `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py dry-run <flow.toml>`: read every state as the LLM will see it.
3. `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py dry-run <flow.toml> --results <labels>`: walk each branch and loop limit of the original skill.

Do not compare the behavior of the old and new skill automatically. The
correspondence table below is the check.

## 4. Show a correspondence table and get confirmation

Show the user a table that maps every step, branch and loop of the original
`SKILL.md` to where it ended up:

| original (section or line) | new place (state id, choice, or `SKILL.md`) | note |
|---|---|---|

Every original step must appear. Mark anything dropped, merged, split, or
given a new loop limit in the note column. Ask the user to confirm the table.
If they object, fix the definition and show the table again.

## 5. Rewrite `SKILL.md`

After the user confirms, reduce `SKILL.md` to the context and domain knowledge
plus a fixed loop: run
`uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py start <flow.toml>`, follow the
output, run the `next` command it prints, and repeat until it prints
`Flow complete.` Add `allowed-tools` for the `flow.py` command, and bundle the
engine with a relative symlink to `shared/flow/flow.py`.
