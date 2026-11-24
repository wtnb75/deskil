# deskil marketplace

Claude Code plugin marketplace.

## Install

```
/plugin marketplace add wtnb75/deskil
/plugin install deskil@deskil
/plugin install deskil-dev@deskil
```

## The `deskil` command

Skills that run on a flow definition call the `deskil` command, which you install once per machine
(it needs [uv](https://docs.astral.sh/uv/)):

```
uv tool install git+https://github.com/wtnb75/deskil   # install
uv tool upgrade deskil                                 # update
deskil --version
```

Skills check `deskil --version` first and tell you to install it when it is missing.

Earlier versions had you copy (or symlink) `flow.py` into every skill and call it by its path. That is no
longer needed. If you did, migrate a skill like this:

1. Install `deskil` as above.
2. Delete the copied `flow.py` and the task that synchronises it.
3. In `SKILL.md`, replace each call of the copy (for example `uv run <path>/flow.py start flow.toml`) with
   `deskil flow start flow.toml`, and set `allowed-tools: Bash(deskil --version), Bash(deskil flow:*)`.
4. Put the install check (see any skill of the `deskil` plugin) first in the body.

## Layout

```
.claude-plugin/marketplace.json   marketplace catalog
shared/scripts/                   scripts shared by plugins (single source of truth)
shared/flow/flow.py               the flow engine
shared/flow/deskil.py             the `deskil` entry point (`deskil flow ...` runs the engine)
pyproject.toml                    packages the two modules above as the `deskil` command
shared/backlog/backlog.py         the backlog tool
plugins/<name>/
  .claude-plugin/plugin.json
  skills/                         skills
  scripts/<file> -> ../../../shared/scripts/<file>   relative symlink
```

## Plugins

| Plugin | What it is |
|---|---|
| `deskil` | Skills for writing, reviewing, debugging and converting to and from flow definitions (`flow-author`, `flow-review`, `flow-convert`, `flow-export`). |
| `deskil-dev` | Skills for the backlog workflow, each written as a flow: `add`, `prio`, `decide`, `impl`. |
| `feature-a` | Sample plugin. Includes `review-loop`, a skill written as a flow. |
| `feature-b` | Sample plugin that uses the shared script. |

## Flow engine

Skills are often written as long, numbered procedures. The flow engine
(`shared/flow/flow.py`, run as `deskil flow ...`; Python 3.11+, standard library only) runs them as a
state machine instead: the procedure lives in a `flow.toml`, and the engine
prints only the current step, its notes, and the results the LLM can report.

```
deskil flow lint <flow.toml> [--format text|json|github]  # find orphans, dead ends, bad references
deskil flow dry-run <flow.toml> [--results a,b,c]  # see the steps without running
deskil flow test <flow.toml> <scenarios.toml>      # check [[scenario]] name/choices/expect against the flow
deskil flow graph <flow.toml>                      # print the transitions as a Mermaid flowchart
deskil flow rename <flow.toml> <old> <new> [--allow-end]  # rename a state in this file; any `end = true` state needs --allow-end (the tool cannot tell a part from a root, and includers' `exits` keys are not updated)
deskil flow new <flow.toml>                        # write a template definition (never overwrites)
deskil flow fmt <flow.toml> [--check]              # sort keys, normalise layout, keep comments
deskil flow runs                                   # list runs (id, status, updated, definition)
deskil flow gc --older-than DAYS --done            # delete old and/or ended runs (filters are ANDed)
deskil flow gc --corrupt                           # delete unreadable run files (e.g. left by a killed start)
deskil flow stats RUN_ID --json                    # per-state visits and on_exceed entries of a run
deskil flow usage RUN_ID... [--save] [--json]      # per-state token usage of one or more runs (a table, or JSON)
deskil flow graph <flow.toml> --usage RUN_ID...    # the same Mermaid flowchart, with mean tokens and visits per state
deskil flow export <flow.toml> [--lang en|ja]      # print the plain-skill text (dropped items to stderr)
deskil flow start <flow.toml> [--ref main]         # start a run, print the first step
deskil flow next <run-id> [--result <label>]       # report a result, print the next step
deskil flow status <run-id>                        # where is this run?
```

A definition may name the oldest engine it needs with `engine = ">=1.4"` (only `>=`, at the top level of the
root definition). An older `deskil` stops with a message to run `uv tool upgrade deskil`; without `engine` a
definition runs on any version.

A state may carry `run = ["cmd", "arg"]`; flow then runs it and shows the exit code and
output. Commands run only if the definition is identical to its copy at `--ref`
(default `main`); otherwise they are shown but not executed. This includes a plugin
installed from a marketplace: its directory is not a git repository, so the commands of
its flows are only shown, and the prompt tells the assistant to run them itself.
In a `run` argument, `${DEF_DIR}` is replaced by the directory of the definition file
(for example `"${DEF_DIR}/../../scripts/x.py"`); no other variable is expanded.

Run state is stored in `.flow/runs/` of the git root (of the working directory outside a repository)
(override with `--state-dir` or `FLOW_STATE_DIR`). `next` locks the run (`flock` on `<run id>.lock`)
and fails at once if another process holds it; this works on macOS and Linux only (no locking on Windows). See
`plugins/feature-a/skills/review-loop/` for a complete example, and
`docs/superpowers/specs/2026-11-22-flow-engine-design.md` for the design (in Japanese).

Token usage per state comes from the Claude Code session log, found through `CLAUDE_CODE_SESSION_ID`
(recorded in the run at `start`); a run made outside Claude Code has no usage. When a run ends, the engine
saves the result to `<state-dir>/<run_id>/usage.json`. Use `usage --save` to write it for a run that is
still going or that ended before this feature existed. Claude Code may delete old session logs, so the saved
file is what survives; `usage` and `graph --usage` fall back to it when the log is gone. `gc` removes
`usage.json` together with the run.

Limitations: usage is read from the session that started the run. A run driven from inside a subagent
reports 0 main-session turns and tool calls (its tokens appear only as `sub_total`). Subagents that run at
the same time as a run are counted into whichever state is open. Two runs active in one session count each
other's subagent tokens. A run continued from another session is not counted after the switch, and `next`
prints a warning.

## Backlog workflow

`docs/BACKLOG.md` holds the ideas that are not done yet (items `B-NNN` with a state, a priority `P1`-`P3`,
and optional dependencies). The `deskil-dev` skills drive it:

```
add      write a new todo item
prio     propose priorities, apply them after you approve
decide   compare approaches, record the decision (todo -> ready, or dropped)
impl     implement a ready item on a branch, review the change once, open a pull request, mark it done
```

The skills call `shared/backlog/backlog.py` (Python 3.11+, standard library only) so that ids, formats and moves are exact:

```
uv run backlog.py list [--all | --status todo,ready]   # ordered by state, priority, id; marks blocked items
uv run backlog.py show <ID>
uv run backlog.py next-id                               # also looks at origin (default branch, newest unmerged origin/backlog/* and origin/docs/*; run `git fetch` first)
uv run backlog.py lint                                 # exit 1 when the format is broken
uv run backlog.py lint --against origin/main           # also flag ids that origin/main uses for a different item
uv run backlog.py set <ID> <key> <value>               # one single-line field (状態 / 優先度 / 依存 / 完了 / PR)
uv run backlog.py archive <ID> --done [--pr <N>]       # or --dropped; moves the item to "done / dropped"
```

The file defaults to `docs/BACKLOG.md`, searched upward from the working directory up to the git root (override with `--file`, which skips the search). Writes are refused when they would add a lint problem.

## Development

```
task test   # pytest
task lint   # ruff
uv tool install --editable .   # make the installed `deskil` use this working tree
```

Without the editable install, the `deskil-dev` skills run the installed (released) engine, not the
`flow.py` you are editing.

## Notes

- Shared scripts (`backlog.py`, `common.sh`) are bundled into each plugin through **relative symlinks**
  (plugins are copied to a cache on install and cannot reference files outside their own directory).
- Symlinks require `core.symlinks` support: macOS / Linux only (Windows is not supported).
- Links must be relative and point inside this repository.
- Keep the executable bit on `shared/scripts/*`.

## Local test

```
/plugin marketplace add ./
/plugin install feature-a@deskil
```

Then check that `~/.claude/plugins/cache/` contains a real file (not a dangling link) for `scripts/common.sh`.
