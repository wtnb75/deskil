# deskil marketplace

Claude Code plugin marketplace.

## Install

```
/plugin marketplace add <github-user>/<repo>
/plugin install feature-a@deskil
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
