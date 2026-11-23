---
name: flow-export
description: Convert a skill driven by a deskil flow definition back into an ordinary skill that needs no engine, and report what the conversion cannot keep
allowed-tools: Bash(deskil --version), Bash(deskil flow:*)
---

Before anything else, run `deskil --version`. If the command is not found, tell the user to run `uv tool install git+https://github.com/wtnb75/deskil` and stop.

Turn a skill that runs on a deskil flow definition (`flow.toml`) back into an
ordinary `SKILL.md`. This is the reverse of `flow-convert`.

Run this skill as a step-by-step flow.

1. Run `deskil flow start ${CLAUDE_PLUGIN_ROOT}/skills/flow-export/flow.toml`.
2. Follow the instructions in the output. When the work is done, run the `next` command shown at the end of the output.
3. Repeat until the output ends with `Flow complete.`

## How to read the exported text

The text uses only symbols and ids, so it does not depend on a language:

| in the text | meaning |
|---|---|
| `Start at ...` (first line) | the start state |
| `## <id>` | a state; the prompt and notes follow, copied as written |
| ``- `<label>` → `<goto>`: <when>`` | a choice: if `<when>` holds, go to `<goto>` |
| ``→ `<goto>` `` | the next state, with no decision |
| ``(at most N times → `<target>`)`` | the state may be entered N times; then go to `<target>` |
| the end line | the procedure ends here |
