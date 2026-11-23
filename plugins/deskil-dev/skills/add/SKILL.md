---
name: add
description: Add an idea or a deferred item to docs/BACKLOG.md as a todo item, with a correct id and format
allowed-tools: Bash(deskil flow:*), Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py:*)
---

Before anything else, run `deskil --version`. If the command is not found, tell the user to run `uv tool install git+https://github.com/wtnb75/deskil` and stop.

Run this skill as a step-by-step flow.

In the steps, `backlog.py <args>` means `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py <args>`.

1. Run `deskil flow start ${CLAUDE_PLUGIN_ROOT}/skills/add/flow.toml`.
2. Follow the instructions in the output. When the work is done, run the `next` command shown at the end of the output.
3. Repeat until the output ends with `Flow complete.`
