---
name: review-loop
description: Run the test suite and fix failures, with at most two fix attempts (sample flow skill)
allowed-tools: Bash(deskil flow:*)
---

Before anything else, run `deskil --version`. If the command is not found, tell the user to run `uv tool install git+https://github.com/wtnb75/deskil` and stop.

Run this skill as a step-by-step flow.

1. Run `deskil flow start ${CLAUDE_PLUGIN_ROOT}/skills/review-loop/flow.toml`.
2. Follow the instructions in the output. When the work is done, run the `next` command shown at the end of the output.
3. Repeat until the output ends with `Flow complete.`
