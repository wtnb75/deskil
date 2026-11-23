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


def drop_exceeded_record(sd, rid):
    """Turn a run file into one written before the exceed counts were recorded."""
    p = sd / f"{rid}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    del data["exceeded"]
    p.write_text(json.dumps(data), encoding="utf-8")


def test_stats_refuses_changed_definition_for_old_run(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    drop_exceeded_record(sd, rid)
    write_def(tmp_path, LOOP.replace("max_visits = 2", "max_visits = 3"))
    with pytest.raises(flow.FlowError, match="changed"):
        flow.stats_json(rid, sd)


def test_stats_old_run_falls_back_to_replay(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    flow.next_step(rid, "again", sd, cmd="flow")
    flow.next_step(rid, "again", sd, cmd="flow")
    drop_exceeded_record(sd, rid)
    data = json.loads(flow.stats_json(rid, sd))
    assert data["states"]["work"] == {"visits": 2, "exceeded": 1}
    assert data["exceeded_total"] == 1


def test_old_run_survives_a_save_round_trip(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    drop_exceeded_record(sd, rid)
    flow.next_step(rid, "again", sd, cmd="flow")  # saves "exceeded": null
    flow.next_step(rid, "again", sd, cmd="flow")  # must still load
    data = json.loads(flow.stats_json(rid, sd))
    assert data["states"]["work"] == {"visits": 2, "exceeded": 1}


def test_stats_after_force_counts_only_real_exceeds(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    flow.next_step(rid, "again", sd, cmd="flow")  # work (2nd visit), no exceed
    write_def(tmp_path, LOOP.replace("max_visits = 2", "max_visits = 1"))
    flow.next_step(rid, "done", sd, cmd="flow", force=True)
    data = json.loads(flow.stats_json(rid, sd))
    assert data["states"]["work"]["exceeded"] == 0
    assert data["exceeded_total"] == 0


def test_stats_after_force_keeps_earlier_exceeds(flow, write_def, tmp_path):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    flow.next_step(rid, "again", sd, cmd="flow")
    flow.next_step(rid, "again", sd, cmd="flow")  # exceeds -> stop
    write_def(tmp_path, LOOP.replace("max_visits = 2", "max_visits = 5"))
    flow.next_step(rid, None, sd, cmd="flow", force=True)  # stop -> end
    data = json.loads(flow.stats_json(rid, sd))
    assert data["states"]["work"]["exceeded"] == 1
    assert data["exceeded_total"] == 1


def test_stats_unknown_run(flow, tmp_path):
    with pytest.raises(flow.FlowError):
        flow.stats_json("nope", tmp_path / "runs")


def test_stats_cli_outputs_json(flow, write_def, tmp_path, capsys):
    path = write_def(tmp_path, LOOP)
    sd = tmp_path / "runs"
    rid = new_run(flow, path, sd)
    assert flow.main(["stats", rid, "--state-dir", str(sd), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == rid
