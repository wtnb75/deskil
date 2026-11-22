---
name: flow-author
description: Create or edit a flow definition (flow.toml) from a step-by-step procedure, then check it with lint and dry-run
allowed-tools: Bash(uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py:*)
---

Turn a procedure into a flow definition, or edit an existing one. Every
command below is run exactly as written.

## 1. Understand the procedure

Read the existing skill (or the user's description). List the steps, every
decision ("if X go to ..."), every loop (and its limit), and the notes that
apply to the whole procedure.

## 2. Write `flow.toml` next to the skill

```toml
schema = 1
start = "run_tests"

[notes]
always = ["Notes shown at every step"]
[notes.common]
careful = "Notes shown only at steps that list them"

[states.run_tests]
prompt = "What to do at this step"          # or { file = "prompts/run_tests.md" }
notes = ["careful"]

[[states.run_tests.choices]]                # a decision: one block per outcome
label = "pass"                              # what the LLM reports
when = "All tests passed"                   # the criterion for choosing it
goto = "report"

[states.fix]
prompt = { file = "prompts/fix.md" }
goto = "run_tests"                          # no decision: just continue
max_visits = 2                              # loop limit ...
on_exceed = "report_fail"                   # ... and where to go when it is hit

[states.report]
prompt = "Report the result."
end = true                                  # the flow stops here
```

Rules:

- State ids match `[A-Za-z_][A-Za-z0-9_]*`. Use names, not numbers like `1.1`.
- Labels match `[A-Za-z0-9_]+`. Every choice needs a `when` that says exactly when to pick it.
- Each state has exactly one of `goto`, `[[choices]]`, or `end = true`.
- Put long text in a file: `prompt = { file = "prompts/step.md" }`. Paths are relative to the definition and must stay inside its directory.
- `delegate = "<agent name>"` hands a state to a subagent. The rendered step tells the caller to give the whole step text to that agent, which runs the `next` command itself and returns its output. The agent's model and tools live in the plugin's `agents/` definition, not in the flow. An end state cannot have `delegate`.

## 3. Check it

1. `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py lint <flow.toml>`: fix every error. Read every warning and decide if it is intended.
2. `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py dry-run <flow.toml>`: read every state as the LLM will see it.
3. `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py dry-run <flow.toml> --results fail,fail,fail`: walk the paths that matter, including the loop limit.

## 4. Rename states with the tool

Never rename a state by hand. Use
`uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py rename <flow.toml> <old> <new>`.
It updates every reference and refuses a rename that would break the definition.

## 5. Wire up the skill

The skill's `SKILL.md` only needs a fixed loop: run
`uv run ${CLAUDE_PLUGIN_ROOT}/scripts/flow.py start <flow.toml>`, follow the
output, run the `next` command it prints, and repeat until it prints
`Flow complete.` Add `allowed-tools` for the `flow.py` command, and bundle the
engine with a relative symlink to `shared/flow/flow.py`.
