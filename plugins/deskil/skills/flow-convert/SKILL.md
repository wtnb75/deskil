---
name: flow-convert
description: Convert an existing skill into a skill driven by a deskil flow definition, with a correspondence table for the user to confirm
allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)
---

Convert an existing skill (`SKILL.md`) into a skill that runs on a deskil flow
definition. Writing the definition itself follows `flow-author`.

Run this skill as a step-by-step flow.

1. Run `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py start ${CLAUDE_PLUGIN_ROOT}/skills/flow-convert/flow.toml`.
2. Follow the instructions in the output. When the work is done, run the `next` command shown at the end of the output.
3. Repeat until the output ends with `Flow complete.`

## What moves and what stays

| Moves to `flow.toml` | Stays in `SKILL.md` |
|---|---|
| ordered steps | purpose and when to use the skill |
| branches ("if X, do Y") | context and domain knowledge |
| loops and their limits (retry at most N times) | background the steps rely on, glossary, examples |
| notes that apply to the whole procedure or to some steps | |
