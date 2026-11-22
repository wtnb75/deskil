"""`flow stats <run-id> --json`: per-state visits and on_exceed entries of one run."""

import json
import re

import pytest

LOOP = """schema = 1
start = "work"
[states.work]
prompt = "W"
max_visits = 2
on_exceed = "stop"
choices = [{ label = "again", when = "more", goto = "work" }, { label = "done", when = "finished", goto = "end" }]
[states.stop]
prompt = "S"
goto = "end"
[states.end]
prompt = "E"
end = true
"""


def new_run(flow, path, state_dir):
    out = flow.start_run(path, state_dir, cmd="flow")
    return re.search(r"\(run: ([^)]+)\)", out).group(1)


def test_stats_counts_visits_and_exceed(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    flow.next_step(rid, "again", sd, cmd="flow")  # work (2nd visit)
    flow.next_step(rid, "again", sd, cmd="flow")  # over the limit -> stop
    data = json.loads(flow.stats_json(rid, sd))
    assert data["run_id"] == rid
    assert data["status"] == "running"
    assert data["states"]["work"] == {"visits": 2, "exceeded": 1}
    assert data["states"]["stop"] == {"visits": 1, "exceeded": 0}
    assert data["exceeded_total"] == 1


def test_stats_without_exceed(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    flow.next_step(rid, "done", sd, cmd="flow")
    data = json.loads(flow.stats_json(rid, sd))
    assert data["status"] == "ended"
    assert data["states"]["work"] == {"visits": 1, "exceeded": 0}
    assert data["exceeded_total"] == 0


def test_stats_refuses_changed_definition(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    write_def(tmp_path, LOOP.replace("max_visits = 2", "max_visits = 3"))
    with pytest.raises(flow.FlowError, match="changed"):
        flow.stats_json(rid, sd)


def test_stats_unknown_run(flow, tmp_path):
    with pytest.raises(flow.FlowError):
        flow.stats_json("nope", tmp_path / "runs")


def test_stats_cli_outputs_json(flow, write_def, tmp_path, capsys):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    assert flow.main(["stats", rid, "--state-dir", str(sd), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == rid
