---
name: flow-author
description: Create or edit a flow definition (flow.toml) from a step-by-step procedure, then check it with lint and dry-run
allowed-tools: Bash(deskil --version), Bash(deskil flow:*)
---

Before anything else, run `deskil --version`. If the command is not found, tell the user to run `uv tool install git+https://github.com/wtnb75/deskil` and stop.

Turn a procedure into a flow definition, or edit an existing one. Every
command below is run exactly as written.

## 1. Understand the procedure

Read the existing skill (or the user's description). List the steps, every
decision ("if X go to ..."), every loop (and its limit), and the notes that
apply to the whole procedure.

## 2. Write `flow.toml` next to the skill

For a new definition, start from the template:
`deskil flow new <flow.toml>` (it refuses to overwrite an existing file), then replace its states (the template is a small do_work, check, fix, report flow). An example that shows the common keys:

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
- `gate = true` makes a state need the user's approval. The rendered step tells the caller to ask the user (for example with `AskUserQuestion`) and not to go on if rejected; leaving the state needs `deskil flow next --approval "<the user's answer>"` (an error without it), and the answer is recorded in the run's history with the time. The engine cannot check the answer is real, so this is a record, not enforcement. An end state cannot have `gate`, and `gate` cannot be combined with `delegate` (a subagent cannot ask the user).
- `run = ["cmd", "arg", ...]` makes flow run a fixed command when the state is entered and show the exit code and output to the LLM (the LLM still decides the branch). It is an argument list, never passed through a shell; for a pipe write `["sh", "-c", "..."]`. Options, valid only with `run`: `timeout` (seconds, default 300; the exit code is then shown as `timeout`), `cwd` (relative to the definition, default where `start` ran), `output_lines` (last N lines of stdout and stderr, each, default 100; the full text is saved in the run directory). An end state cannot have `run`. In a `run` argument, `${DEF_DIR}` is replaced by the absolute path of the definition's directory, so a flow can point at a script in its own plugin (`["uv", "run", "${DEF_DIR}/../../scripts/x.py"]`); no other `${...}` is expanded (lint warns), and `cwd` does not expand it.
- A command runs only if the definition file is identical to its copy at the git ref given to `start --ref` (default `main`). Otherwise the command is only shown ("not executed"), so an edited, uncommitted definition cannot run anything. `dry-run` never runs commands.
- `include = "parts/x.toml"` with `exits = { <end state id of the part> = "<state id here>" }` replaces a state by the states of another definition (a part), so a shared procedure is written once. An include state takes only `include` and `exits`; `exits` must name every end state of the part. The part's states become `<include state>__<state>` after loading. The part has its own `notes` (they apply only to its states) and its `{ file }` / `cwd` / `${DEF_DIR}` paths are relative to the part's directory. The path must stay inside the definition's directory and cannot contain `..`; a symlink there is how a part is shared between skills, but it must not point outside the repository. Includes may nest but not loop. A command runs only if the root, every part and every `{ file }` text match the git ref.

## 3. Check it

1. `deskil flow fmt <flow.toml>`: sort the keys and normalise the layout in place. Comments are kept (a comment line stays with the key below it); the command refuses to write if the data would change. Run it after every edit, before lint.
2. `deskil flow lint <flow.toml>`: fix every error. Read every warning and decide if it is intended.
3. `deskil flow dry-run <flow.toml>`: read every state as the LLM will see it.
4. `deskil flow dry-run <flow.toml> --results fail,fail,fail`: walk the paths that matter, including the loop limit.

## 4. Rename states with the tool

Never rename a state by hand. Use
`deskil flow rename <flow.toml> <old> <new>`.
It updates every reference in that file and refuses a rename that would break the definition.
It does not touch other files: an end state (`end = true`) of a part is named by the `exits` keys
of the include states in every includer, so renaming one is refused. If you really need it, rename
the `exits` keys in each includer by hand, then re-run with `--allow-end`.

## 5. Wire up the skill

The skill's `SKILL.md` only needs a fixed loop: run
`deskil flow start <flow.toml>`, follow the
output, run the `next` command it prints, and repeat until it prints
`Flow complete.` Add `allowed-tools: Bash(deskil --version), Bash(deskil flow:*)`, and put this sentence first in
the body: "Before anything else, run `deskil --version`. If the command is not found, tell the user to run `uv tool install git+https://github.com/wtnb75/deskil` and stop."
