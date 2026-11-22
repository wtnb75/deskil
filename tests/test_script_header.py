from pathlib import Path

HEADER = '# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\n'


def test_engine_declares_python_version_for_uv_run(flow):
    # `uv run flow.py` reads this block, so it picks a Python that has tomllib.
    assert HEADER in Path(flow.__file__).read_text(encoding="utf-8")
