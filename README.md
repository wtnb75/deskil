# deskil marketplace

Claude Code plugin marketplace.

## Install

```
/plugin marketplace add wtnb75/deskil
/plugin install deskil@deskil
```

## Layout

```
.claude-plugin/marketplace.json   marketplace catalog
shared/scripts/                   scripts shared by plugins (single source of truth)
plugins/<name>/
  .claude-plugin/plugin.json
  skills/                         skills
  scripts/<file> -> ../../../shared/scripts/<file>   relative symlink
```

## Plugins

| Plugin | What it is |
|---|---|
| `deskil` | Skills for writing, reviewing and debugging flow definitions (`flow-author`, `flow-review`). |
| `feature-a` | Sample plugin. Includes `review-loop`, a skill written as a flow. |
| `feature-b` | Sample plugin that uses the shared script. |

## Flow engine

Skills are often written as long, numbered procedures. The flow engine
(`shared/flow/flow.py`, Python 3.11+, standard library only) runs them as a
state machine instead: the procedure lives in a `flow.toml`, and the engine
prints only the current step, its notes, and the results the LLM can report.

```
uv run flow.py lint <flow.toml>                       # find orphans, dead ends, bad references
uv run flow.py dry-run <flow.toml> [--results a,b,c]  # see the steps without running
uv run flow.py rename <flow.toml> <old> <new>         # rename a state everywhere
uv run flow.py start <flow.toml>                      # start a run, print the first step
uv run flow.py next <run-id> [--result <label>]       # report a result, print the next step
uv run flow.py status <run-id>                        # where is this run?
```

Run state is stored in `.flow/runs/` of the working directory
(override with `--state-dir` or `FLOW_STATE_DIR`). See
`plugins/feature-a/skills/review-loop/` for a complete example, and
`docs/superpowers/specs/2026-11-22-flow-engine-design.md` for the design (in Japanese).

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
