"""The deskil command is installable with `uv tool install`."""

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_metadata():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "deskil"
    assert project["scripts"] == {"deskil": "deskil:main"}
    assert project["requires-python"] == ">=3.11"
    assert project["dependencies"] == []
    assert "version" in project["dynamic"]


def test_usage_module_is_packaged():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "usage" in data["tool"]["setuptools"]["py-modules"]
    assert (ROOT / "shared" / "flow" / "usage.py").is_file()


def test_timeline_module_is_packaged():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "timeline" in data["tool"]["setuptools"]["py-modules"]
    assert (ROOT / "shared" / "flow" / "timeline.py").is_file()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_install_and_run_outside_the_repo(tmp_path):
    tools = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    work = tmp_path / "work"
    work.mkdir()
    env = {
        **{k: v for k, v in os.environ.items() if k != "FLOW_CMD"},
        "UV_TOOL_DIR": str(tools),
        "UV_TOOL_BIN_DIR": str(bin_dir),
    }

    def run(*cmd):
        return subprocess.run(
            cmd, cwd=work, env=env, capture_output=True, text=True, check=False
        )

    install = run("uv", "tool", "install", "--from", str(ROOT), "deskil")
    assert install.returncode == 0, install.stderr
    deskil = str(bin_dir / "deskil")

    version = run(deskil, "--version")
    assert (version.returncode, version.stdout) == (0, "deskil 1.0.0\n")
    new = run(deskil, "flow", "new", "x.toml")
    assert new.returncode == 0, new.stderr
    # outside the repository no `#:schema` line is written: there is no schema file to point at
    assert not (work / "x.toml").read_text(encoding="utf-8").startswith("#:schema")
    lint = run(deskil, "flow", "lint", "x.toml")
    assert (lint.returncode, lint.stdout) == (0, "")
