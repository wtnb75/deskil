---
name: flow-review
description: Review a flow definition, or debug a flow run that went off course, using lint, dry-run and status
allowed-tools: Bash(deskil flow:*)
---

Before anything else, run `deskil --version`. If the command is not found, tell the user to run `uv tool install git+https://github.com/wtnb75/deskil` and stop.

Review a flow definition or debug a run. Every command below is run exactly
as written.

## Review a definition

1. Run `deskil flow lint <flow.toml>` and explain each finding:

   | code | meaning |
   |---|---|
   | `orphan` | no path from `start` reaches the state |
   | `dead-end` | a reachable state cannot reach any `end` state (includes endless loops) |
   | `missing-target` | a `goto` / `on_exceed` names a state that does not exist |
   | `transition-count` | a state needs exactly one of `goto`, `choices`, `end` |
   | `when-missing`, `label-duplicate` | a decision is ambiguous or incomplete |
   | `unbounded-loop` (warning) | a loop whose exit depends only on the LLM's choice |
   | `unused-note`, `single-choice` (warnings) | dead weight; usually safe to remove or simplify |

2. Run `deskil flow dry-run <flow.toml>` and read each state as the LLM will see it.
   Check that every prompt is self-contained and every `when` is clear.
3. Check that the choices of each decision are mutually exclusive and cover
   every outcome, including "something unexpected".
4. Walk the important paths:
   `deskil flow dry-run <flow.toml> --results fail,fail,fail`.
   Confirm each loop limit sends the run where you expect.

## Debug a run

1. Find the run id in the earlier output (`[state] (run: <id>)`), or list `.flow/runs/` at the git root.
2. Run `deskil flow status <id>`. Compare `History` and `Visits` with what should have happened.
   The first step where the reported result does not match the work is the likely cause.
3. Decide whether the fault is in the definition (a vague `when`, a missing
   choice) or in the run (a wrong result was reported). Fix the definition
   with `flow-author`; for the run, continue with the right `next` command.
4. If the definition changed while the run was open, `next` refuses to
   continue. Use `--force` only if the change is intended and the current state still exists.
   `flow runs` marks such runs with `[definition changed]`; remove the ones you no longer need with `flow gc`.
