# deskil marketplace

Claude Code plugin marketplace.

## Install

```
/plugin marketplace add wtnb75/deskil
/plugin install deskil@deskil
/plugin install deskil-dev@deskil
```

## Layout

```
.claude-plugin/marketplace.json   marketplace catalog
shared/scripts/                   scripts shared by plugins (single source of truth)
shared/flow/flow.py               the flow engine
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
(`shared/flow/flow.py`, Python 3.11+, standard library only) runs them as a
state machine instead: the procedure lives in a `flow.toml`, and the engine
prints only the current step, its notes, and the results the LLM can report.

```
uv run flow.py lint <flow.toml> [--format text|json|github]  # find orphans, dead ends, bad references
uv run flow.py dry-run <flow.toml> [--results a,b,c]  # see the steps without running
uv run flow.py test <flow.toml> <scenarios.toml>      # check [[scenario]] name/choices/expect against the flow
uv run flow.py graph <flow.toml>                      # print the transitions as a Mermaid flowchart
uv run flow.py rename <flow.toml> <old> <new>         # rename a state everywhere
uv run flow.py new <flow.toml>                        # write a template definition (never overwrites)
uv run flow.py fmt <flow.toml> [--check]              # sort keys, normalise layout, keep comments
uv run flow.py runs                                   # list runs (id, status, updated, definition)
uv run flow.py gc --older-than DAYS --done            # delete old and/or ended runs (filters are ANDed)
uv run flow.py stats RUN_ID --json                    # per-state visits and on_exceed entries of a run
uv run flow.py export <flow.toml> [--lang en|ja]      # print the plain-skill text (dropped items to stderr)
uv run flow.py start <flow.toml> [--ref main]         # start a run, print the first step
uv run flow.py next <run-id> [--result <label>]       # report a result, print the next step
uv run flow.py status <run-id>                        # where is this run?
```

A state may carry `run = ["cmd", "arg"]`; flow then runs it and shows the exit code and
output. Commands run only if the definition is identical to its copy at `--ref`
(default `main`); otherwise they are shown but not executed. This includes a plugin
installed from a marketplace: its directory is not a git repository, so the commands of
its flows are only shown, and the prompt tells the assistant to run them itself.
In a `run` argument, `${DEF_DIR}` is replaced by the directory of the definition file
(for example `"${DEF_DIR}/../../scripts/x.py"`); no other variable is expanded.

Run state is stored in `.flow/runs/` of the working directory
(override with `--state-dir` or `FLOW_STATE_DIR`). See
`plugins/feature-a/skills/review-loop/` for a complete example, and
`docs/superpowers/specs/2026-11-22-flow-engine-design.md` for the design (in Japanese).

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
uv run backlog.py next-id                               # also looks at origin (default branch, newest origin/backlog/* and origin/docs/*; run `git fetch` first)
uv run backlog.py lint                                 # exit 1 when the format is broken
uv run backlog.py set <ID> <key> <value>               # one single-line field (状態 / 優先度 / 依存 / 完了 / PR)
uv run backlog.py archive <ID> --done [--pr <N>]       # or --dropped; moves the item to "done / dropped"
```

The file defaults to `docs/BACKLOG.md` (override with `--file`). Writes are refused when they would add a lint problem.

## Development

```
task test   # pytest
task lint   # ruff
```

## Notes

- Shared scripts are bundled into each plugin through **relative symlinks**
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
