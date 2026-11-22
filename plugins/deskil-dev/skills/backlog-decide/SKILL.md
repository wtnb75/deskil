---
name: backlog-decide
description: Pick a todo item in docs/BACKLOG.md, compare approaches with the user, record the decision and make the item ready (or drop it)
allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*), Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py:*)
---

Run this skill as a step-by-step flow.

In the steps, `backlog.py <args>` means `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py <args>`.

1. Run `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py start ${CLAUDE_PLUGIN_ROOT}/skills/backlog-decide/flow.toml`.
2. Follow the instructions in the output. When the work is done, run the `next` command shown at the end of the output.
3. Repeat until the output ends with `Flow complete.`
