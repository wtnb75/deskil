"""Shared fixtures for the flow engine tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared" / "flow"))

import flow as _flow  # noqa: E402


@pytest.fixture
def flow():
    """The flow module under test."""
    return _flow


@pytest.fixture
def write_def():
    """Write a definition file and return its path."""

    def _write(tmp_path: Path, text: str, name: str = "flow.toml") -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write
