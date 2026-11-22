import pytest


def test_read_toml_ok(flow, write_def, tmp_path):
    p = write_def(tmp_path, 'start = "a"\n')
    assert flow.read_toml(p) == {"start": "a"}


def test_read_toml_syntax_error_has_path_and_line(flow, write_def, tmp_path):
    p = write_def(tmp_path, "start = \n")
    with pytest.raises(flow.FlowError) as exc:
        flow.read_toml(p)
    assert str(p) in str(exc.value)
    assert "line" in str(exc.value)


def test_read_toml_missing_file(flow, tmp_path):
    with pytest.raises(flow.FlowError):
        flow.read_toml(tmp_path / "nope.toml")
