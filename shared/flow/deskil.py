#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""deskil: the entry point of the deskil command.

It only picks a subcommand and hands the rest of the arguments to it, so that more tools
can be added as `deskil <name> ...` later.
"""

from __future__ import annotations

import sys

# subcommand -> one-line description. Add a tool here and in `_run`.
SUBCOMMANDS: dict[str, str] = {"flow": "step-by-step flow runner"}


def _usage() -> str:
    lines = ["usage: deskil [--version] [-h] <command> [<args>]", "", "commands:"]
    lines += [f"  {name:<8}{desc}" for name, desc in SUBCOMMANDS.items()]
    return "\n".join(lines) + "\n"


def _run(command: str, args: list[str]) -> int:
    # Imported here so that --version and the usage do not load a tool they do not use.
    if command == "flow":
        import flow

        return flow.main(args, prog="deskil flow", cmd="deskil flow")
    raise AssertionError(command)  # SUBCOMMANDS and _run are out of step


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.stderr.write(_usage())
        return 2
    first, rest = argv[0], argv[1:]
    if first == "--version":
        import flow

        print(f"deskil {flow.__version__}")
        return 0
    if first in ("-h", "--help"):
        sys.stdout.write(_usage())
        return 0
    if first not in SUBCOMMANDS:
        sys.stderr.write(f"deskil: unknown command: {first}\n\n{_usage()}")
        return 2
    return _run(first, rest)


if __name__ == "__main__":
    raise SystemExit(main())
