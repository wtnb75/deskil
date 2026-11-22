---
name: flow-export
description: Convert a skill driven by a deskil flow definition back into an ordinary skill that needs no engine, and report what the conversion cannot keep
allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)
---

Turn a skill that runs on a deskil flow definition (`flow.toml`) back into an
ordinary `SKILL.md`. This is the reverse of `flow-convert`. Every command
below is run exactly as written.

## 1. Check the definition

Run `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py lint <flow.toml>` and fix
every error first (see `flow-review`).

## 2. Export the procedure

Run `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py export <flow.toml>`. Add
`--lang en` or `--lang ja` if the detected language of the fixed phrases is
wrong. The text goes to stdout, and the list of dropped information goes to
stderr (`dropped information:`).

The text uses only symbols and ids, so it does not depend on a language:

| in the text | meaning |
|---|---|
| `Start at ...` (first line) | the start state |
| `## <id>` | a state; the prompt and notes follow, copied as written |
| ``- `<label>` → `<goto>`: <when>`` | a choice: if `<when>` holds, go to `<goto>` |
| ``→ `<goto>` `` | the next state, with no decision |
| ``(at most N times → `<target>`)`` | the state may be entered N times; then go to `<target>` |
| the end line | the procedure ends here |

## 3. Write the plain skill

Create or update the skill's `SKILL.md`:

1. Keep its frontmatter `name` and `description`, and its context and domain
   knowledge (the part `flow-convert` left in `SKILL.md`).
2. Replace the "run `flow.py start`" loop with the exported text.
3. Remove the `flow.py` entry from `allowed-tools`. Keep the tools the steps
   themselves need (for example the commands of a `run`).
4. Remove the bundled `flow.py` symlink and the `flow.toml` only if the user
   wants to stop using deskil for this skill; otherwise keep them so the
   skill can be converted again.

## 4. Report what was lost

Show the user the `dropped information` list, and say plainly that these are
no longer enforced by anything:

- `max_visits`: the text says the limit, but no one counts the visits.
- `run`: the command is written in the text; the engine no longer runs it or
  shows its output.
- `delegate`: the text names the subagent; the engine no longer sets it up.
- `gate`: the text asks the user to confirm; the engine no longer records the approval.
- `include`: the parts were merged into one text (ids may be prefixed).
- Prompt files were copied into the text.

## 5. Check the round trip

If the skill came from `flow-convert`, the symbols should match the
definition. Compare the ids, the `` `<label>` → `<goto>` `` lines and the
limits with `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py graph <flow.toml>`
and `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py dry-run <flow.toml>`.
