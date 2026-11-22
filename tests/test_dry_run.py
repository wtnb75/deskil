import pytest

DEF = """\
schema = 1
start = "a"

[states.a]
prompt = "Do A"

[[states.a.choices]]
label = "again"
when = "needs more work"
goto = "w"

[[states.a.choices]]
label = "stop"
when = "enough"
goto = "e"

[states.w]
prompt = "Work"
goto = "a"
max_visits = 3
on_exceed = "e"

[states.e]
prompt = "Done"
end = true
"""


@pytest.fixture(autouse=True)
def fixed_cmd(monkeypatch):
    monkeypatch.setenv("FLOW_CMD", "flow")


@pytest.fixture
def path(write_def, tmp_path):
    return write_def(tmp_path, DEF)


def test_dry_run_all_states(flow, path):
    out = flow.dry_run(path, None, "flow")
    for sid in ("a", "w", "e"):
        assert f"[{sid}] (run: dry-run)" in out
    assert out.count("\n---\n") == 2


def test_dry_run_follows_results_to_end(flow, path):
    out = flow.dry_run(path, ["again", "stop"], "flow")
    order = [out.index(f"[{s}] (run: dry-run)") for s in ("a", "w")]
    assert order == sorted(order)
    assert (
        out.count("[a] (run: dry-run)") == 2
    )  # a -> w -> a (goto step needs no result)
    assert out.rstrip().endswith("Flow complete.")
    assert "results" not in out.split("Flow complete.")[-1]


def test_dry_run_exhausted(flow, path):
    out = flow.dry_run(path, ["again"], "flow")
    assert out.rstrip().endswith("(results exhausted at a)")


def test_dry_run_leftover_results(flow, path):
    out = flow.dry_run(path, ["stop", "again"], "flow")
    assert out.rstrip().endswith("(results left over: again)")


def test_dry_run_invalid_label_raises(flow, path):
    with pytest.raises(flow.FlowError) as exc:
        flow.dry_run(path, ["nope"], "flow")
    assert "again" in str(exc.value)


def test_dry_run_writes_no_files(flow, path, tmp_path):
    flow.dry_run(path, ["again", "stop"], "flow")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["flow.toml"]


def test_dry_run_applies_max_visits(flow, path):
    # w may be entered 3 times; the 4th "again" is redirected to e.
    out = flow.dry_run(path, ["again"] * 4, "flow")
    assert out.rstrip().endswith("Flow complete.")
    assert out.count("[w] (run: dry-run)") == 3


def test_cli_dry_run(flow, path, capsys):
    assert flow.main(["dry-run", str(path), "--results", "again, stop"]) == 0
    assert "[e] (run: dry-run)" in capsys.readouterr().out
    assert flow.main(["dry-run", str(path)]) == 0
    assert capsys.readouterr().out.count("(run: dry-run)") == 3
