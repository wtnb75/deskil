---
name: backlog-decide
description: Pick one todo item, or a batch such as "top 10" or "P2 10", in docs/BACKLOG.md, compare approaches with the user, record the decisions and make the items ready (or drop them)
allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*), Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py:*)
---

Run this skill as a step-by-step flow.

The user may name one item (`B-012`) or a batch: `top 10` (the first 10 by priority) or `P2 10` (the first 10 of
priority P2 or higher). Keep that scope from the request; the flow reads it in its first step.

In the steps, `backlog.py <args>` means `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py <args>`.

1. Run `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py start ${CLAUDE_PLUGIN_ROOT}/skills/backlog-decide/flow.toml`.
2. Follow the instructions in the output. When the work is done, run the `next` command shown at the end of the output.
3. Repeat until the output ends with `Flow complete.`
