"""The JSON Schema for flow.toml (used by Taplo) must agree with the keys the linter knows."""

import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "shared" / "flow" / "flow.schema.json"


@pytest.fixture
def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_top_level_keys_match_linter(flow, schema):
    assert set(schema["properties"]) == flow.TOP_KEYS
    assert schema["required"] == ["schema", "start", "states"]


def test_args_keys_match_linter(flow, schema):
    spec = schema["properties"]["args"]["additionalProperties"]
    assert set(spec["properties"]) == flow.ARG_KEYS


def test_notes_keys_match_linter(flow, schema):
    assert set(schema["properties"]["notes"]["properties"]) == flow.NOTES_KEYS


def test_state_keys_match_linter(flow, schema):
    state = schema["properties"]["states"]["additionalProperties"]
    assert set(state["properties"]) == flow.STATE_KEYS


def test_choice_keys_match_linter(flow, schema):
    state = schema["properties"]["states"]["additionalProperties"]
    choice = state["properties"]["choices"]["items"]
    assert set(choice["properties"]) == flow.CHOICE_KEYS
    assert set(choice["required"]) == flow.CHOICE_KEYS


def test_unknown_keys_are_rejected_everywhere(schema):
    state = schema["properties"]["states"]["additionalProperties"]
    choice = state["properties"]["choices"]["items"]
    tables = [
        schema,
        schema["properties"]["args"]["additionalProperties"],
        schema["properties"]["notes"],
        state,
        choice,
    ]
    assert all(t["additionalProperties"] is False for t in tables if "properties" in t)


def test_every_shipped_definition_uses_only_known_keys(flow):
    """A sanity check that the key sets above cover the real definitions."""
    for path in ROOT.glob("plugins/*/skills/*/flow.toml"):
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        assert set(raw) <= flow.TOP_KEYS, path


def test_taplo_config_points_at_the_schema():
    cfg = tomllib.loads((ROOT / ".taplo.toml").read_text(encoding="utf-8"))
    (rule,) = cfg["rule"]
    assert rule["include"] == ["plugins/*/skills/*/flow.toml"]
    assert (ROOT / rule["schema"]["path"]).resolve() == SCHEMA_PATH


def test_patterns_match_linter(flow, schema):
    state = schema["properties"]["states"]["additionalProperties"]
    assert schema["definitions"]["id"]["pattern"] == flow.ID_RE.pattern
    assert state["properties"]["choices"]["items"]["properties"]["label"][
        "pattern"
    ] == (flow.LABEL_RE.pattern)
    assert state["properties"]["delegate"]["pattern"] == flow.AGENT_RE.pattern


@pytest.fixture
def fake_repo(flow, tmp_path, monkeypatch):
    """A repository layout with a schema file, so the definition can be inside or outside it."""
    schema = tmp_path / "repo" / "shared" / "flow" / "flow.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(flow, "SCHEMA_FILE", schema)
    return tmp_path / "repo"


def test_new_definition_points_at_the_schema(flow, fake_repo):
    p = fake_repo / "plugins" / "x" / "skills" / "y" / "flow.toml"
    flow.new_definition(p)
    first = p.read_text(encoding="utf-8").splitlines()[0]
    assert first == "#:schema ../../../../shared/flow/flow.schema.json"
    assert (p.parent / first.removeprefix("#:schema ")).resolve() == flow.SCHEMA_FILE


def test_new_definition_outside_the_repo_has_no_directive(flow, fake_repo, tmp_path):
    p = tmp_path / "elsewhere" / "flow.toml"
    flow.new_definition(p)
    assert p.read_text(encoding="utf-8") == flow.NEW_TEMPLATE


def test_new_definition_without_schema_file_has_no_directive(
    flow, tmp_path, monkeypatch
):
    monkeypatch.setattr(flow, "SCHEMA_FILE", tmp_path / "missing.json")
    p = tmp_path / "flow.toml"
    flow.new_definition(p)
    assert p.read_text(encoding="utf-8") == flow.NEW_TEMPLATE


def test_new_definition_leaves_no_file_when_the_directive_fails(
    flow, fake_repo, monkeypatch
):
    def boom(*_):
        raise RuntimeError("boom")

    monkeypatch.setattr(flow.os.path, "relpath", boom)
    p = fake_repo / "flow.toml"
    with pytest.raises(RuntimeError):
        flow.new_definition(p)
    assert not p.exists()
