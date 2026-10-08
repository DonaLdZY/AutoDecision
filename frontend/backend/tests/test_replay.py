from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import app
from replay import ReplayRecorder, bundle, project, read_events, sanitize


def task_data(**changes):
    return {"id": "replay-task", "task_name": "sales", "status": "completed", "phase": "completed", "run_dir": "runs/sales", "run_started_at": 100.0, "created_at": 90.0, "updated_at": 200.0, **changes}


def node_data(node_id="n1", **changes):
    return {"id": node_id, "parent_id": None, "stage": "draft", "created_time": 110.0, "finish_time": 130.0, "code": "model.fit(train)", "plan": "fit model", "result": "MAE=5", "metric": 5.0, "maximize": False, "is_buggy": False, "is_valid": True, "delivery_ready": True, "search_eligible": True, "visits": 12, "total_reward": 42.0, "uct": 0.8, **changes}


def fixture_snapshot():
    return {
        "auto_realize": {"events": [{"ts": 100, "component": "data_cognition", "event": "started"}, {"ts": 105, "component": "task_definition", "event": "completed"}], "description_text": "Forecast next month", "main_task_protocol": {"metric": "MAE"}},
        "auto_ml": {"nodes": [node_data(), node_data("n2", parent_id="n1", stage="fusion", fusion_sources=["n1", "n3"], created_time=140, finish_time=170, metric=3.0)], "pending_nodes": [], "best_solution_code": "best_model", "best_metric_text": "3.0"},
        "auto_report": {"events": [{"ts": 180, "component": "report", "event": "started"}], "report_markdown": "Best MAE: 3.0"},
    }


def event_sequence(replay, label):
    return next(row["sequence"] for row in replay["events"] if row["label"] == label)


def test_legacy_replay_withholds_future_node_evidence_and_report():
    replay = bundle(task_data(), fixture_snapshot(), [])
    created = project(replay["events"], event_sequence(replay, "node_created n1"))
    node = created["auto_ml"]["pending_nodes"][0]
    assert node["metric"] is None
    assert "code" not in node and "result" not in node
    assert "visits" not in node
    assert created["auto_ml"]["best_node_id"] is None
    assert "report_markdown" not in created["auto_report"]
    first = project(replay["events"], event_sequence(replay, "node_finished n1"))
    assert first["auto_ml"]["best_node_id"] == "n1"
    assert first["auto_ml"]["pending_nodes"] == []
    assert first["auto_ml"]["nodes"][0]["metric"] == 5
    assert "visits" not in first["auto_ml"]["nodes"][0]
    assert "best_solution_code" not in first["auto_ml"]
    final = project(replay["events"], len(replay["events"]))
    assert final["auto_ml"]["best_node_id"] == "n2"
    assert final["auto_ml"]["nodes"][0]["visits"] == 12
    assert final["auto_report"]["report_markdown"] == "Best MAE: 3.0"
    assert final["auto_ml"]["nodes"][1]["parent_ids"] == ["n1", "n3"]
    assert replay["fidelity"] == "reconstructed"


def test_backward_seek_returns_independent_state():
    replay = bundle(task_data(), fixture_snapshot(), [])
    final = project(replay["events"], len(replay["events"]))
    initial = project(replay["events"], 0)
    assert initial["auto_ml"]["nodes"] == []
    assert initial["auto_report"] == {"events": []}
    final["auto_ml"]["nodes"][0]["metric"] = -999
    again = project(replay["events"], len(replay["events"]))
    assert again["auto_ml"]["nodes"][0]["metric"] == 5


def test_unknown_created_time_does_not_invent_generation_state():
    snapshot = {"auto_ml": {"nodes": [node_data(created_time=None)]}}
    replay = bundle(task_data(), snapshot, [])
    assert not any(row["label"] == "node_created n1" for row in replay["events"])
    assert any(row["label"] == "node_finished n1" for row in replay["events"])


def test_recording_persists_node_replacements_and_survives_restart(tmp_path: Path):
    recorder = ReplayRecorder()
    task = task_data(status="running", phase="automl")
    pending = node_data(status="executing", pending_execution=True, metric=None, code="training", visits=0)
    recorder.capture(tmp_path, task, {"auto_ml": {"log_dir": "run/one", "pending_nodes": [pending]}}, 110)
    restarted = ReplayRecorder()
    restarted.capture(tmp_path, task, {"auto_ml": {"log_dir": "run/one", "pending_nodes": [pending]}}, 120)
    rows = read_events(recorder.path(tmp_path, task["id"]))
    assert len([row for row in rows if row["kind"] == "node"]) == 1
    restarted.capture(tmp_path, task, {"auto_ml": {"log_dir": "run/one", "nodes": [node_data()]}}, 130)
    rows = read_events(recorder.path(tmp_path, task["id"]))
    historical = project(rows, rows[1]["sequence"])
    assert historical["auto_ml"]["pending_nodes"][0]["metric"] is None
    final = project(rows, rows[-1]["sequence"])
    assert not final["auto_ml"]["pending_nodes"]
    assert final["task"]["status"] == "running"
    assert final["auto_ml"]["nodes"][0]["metric"] == 5
    assert final["auto_ml"]["nodes"][0]["code"] == "model.fit(train)"


def test_new_search_clears_previous_nodes(tmp_path: Path):
    recorder = ReplayRecorder()
    task = task_data(status="running", phase="automl")
    recorder.capture(tmp_path, task, {"auto_ml": {"log_dir": "one", "nodes": [node_data()]}}, 130)
    recorder.capture(tmp_path, task, {"auto_ml": {"log_dir": "two", "nodes": [node_data("other")]}}, 140)
    rows = read_events(recorder.path(tmp_path, task["id"]))
    final = project(rows, rows[-1]["sequence"])
    assert [node["id"] for node in final["auto_ml"]["nodes"]] == ["other"]


def test_new_search_clears_prior_model_report_and_event_digests(tmp_path: Path):
    recorder = ReplayRecorder()
    task = task_data(status="running", phase="automl")
    event = {"event": "started", "component": "automl"}
    recorder.capture(tmp_path, task, {"auto_ml": {"log_dir": "one", "nodes": [node_data()], "events": [event], "best_solution_code": "old model", "best_metric_text": "5", "resource_usage": {"memory_mb": 400}}, "auto_report": {"report_markdown": "old report", "report": {"winner": "n1"}}}, 130)
    recorder = ReplayRecorder()
    recorder.capture(tmp_path, task, {"auto_ml": {"log_dir": "two", "nodes": [node_data()], "events": [event]}}, 140)
    rows = read_events(recorder.path(tmp_path, task["id"]))
    final = project(rows, rows[-1]["sequence"])
    assert final["auto_ml"]["best_solution_code"] == ""
    assert final["auto_ml"]["best_metric_text"] == ""
    assert final["auto_ml"]["resource_usage"] == {}
    assert final["auto_ml"]["events"] == [event]
    assert final["auto_report"]["report_markdown"] == ""
    assert final["auto_report"]["report"] == {}
    assert len([row for row in rows if row["kind"] == "node"]) == 2


def test_full_rerun_clears_all_stages_and_starts_current_run_bundle(tmp_path: Path):
    recorder = ReplayRecorder()
    old = fixture_snapshot()
    recorder.capture(tmp_path, task_data(), old, 200)
    reset_task = task_data(status="idle", phase="config", run_dir=None, run_started_at=None, updated_at=300)
    recorder.reset_task(tmp_path, reset_task, 300)
    task = task_data(status="running", phase="autorealize", run_started_at=301, updated_at=302)
    current = {"auto_realize": {"current_state": {"status": "running"}}, "auto_ml": {}, "auto_report": {}}
    recorder.capture(tmp_path, task, current, 302)
    rows = read_events(recorder.path(tmp_path, task["id"]))
    final = project(rows, rows[-1]["sequence"])
    assert final["task"]["phase"] == "autorealize"
    assert final["auto_realize"]["description_text"] == ""
    assert final["auto_realize"]["events"] == []
    assert final["auto_ml"]["nodes"] == []
    assert final["auto_ml"]["best_node_id"] is None
    assert final["auto_ml"]["best_solution_code"] == ""
    assert final["auto_report"]["report_markdown"] == ""
    replay = bundle(task, current, rows)
    assert replay["events"][0]["label"] == "task_reset"
    assert replay["started_at"] == 300
    assert not any(row["kind"] == "node" for row in replay["events"])


def test_full_rerun_restart_allows_identical_evidence_in_the_new_run(tmp_path: Path):
    task = task_data(status="running", phase="automl")
    snapshot = fixture_snapshot()
    recorder = ReplayRecorder()
    recorder.capture(tmp_path, task, snapshot, 200)
    recorder.reset_task(tmp_path, task_data(status="idle", phase="config", run_dir=None, run_started_at=None), 300)
    recorder = ReplayRecorder()
    recorder.capture(tmp_path, task, snapshot, 400)
    rows = read_events(recorder.path(tmp_path, task["id"]))
    reset = next(index for index, row in enumerate(rows) if row["label"] == "task_reset")
    assert len([row for row in rows[reset:] if row["kind"] == "node"]) == 2
    final = project(rows, rows[-1]["sequence"])
    assert final["auto_realize"]["events"] == snapshot["auto_realize"]["events"]
    assert final["auto_realize"]["description_text"] == "Forecast next month"
    assert final["auto_report"]["report_markdown"] == "Best MAE: 3.0"


def test_resume_with_new_start_time_keeps_prior_search_evidence(tmp_path: Path):
    recorder = ReplayRecorder()
    recorder.capture(tmp_path, task_data(), {"auto_ml": {"log_dir": "one", "nodes": [node_data()], "best_solution_code": "retained model"}}, 200)
    resumed = task_data(status="running", phase="autorealize", run_started_at=300)
    recorder = ReplayRecorder()
    recorder.capture(tmp_path, resumed, {"auto_realize": {"current_state": {"status": "running"}}, "auto_ml": {}}, 300)
    recorder.capture(tmp_path, {**resumed, "phase": "automl"}, {"auto_ml": {"log_dir": "one", "nodes": [node_data()]}}, 310)
    rows = read_events(recorder.path(tmp_path, resumed["id"]))
    final = project(rows, rows[-1]["sequence"])
    assert len(final["auto_ml"]["nodes"]) == 1
    assert final["auto_ml"]["best_solution_code"] == "retained model"
    assert not any(row["label"] in {"search_reset", "task_reset"} for row in rows)


def test_gateway_runtime_reset_records_explicit_run_boundary(tmp_path: Path, monkeypatch):
    task = app.TaskModel.model_validate({**task_data(), "input_root": str(tmp_path), "output_root": str(tmp_path), "config": {"task_name": "sales", "input_root": str(tmp_path), "output_root": str(tmp_path)}})
    recorder = ReplayRecorder()
    recorder.capture(tmp_path, task.model_dump(), fixture_snapshot(), 200)
    store = app.TaskStore.__new__(app.TaskStore)
    store._lock = threading.Lock()
    store._tasks = {task.id: task}
    store._persist = lambda: None
    monkeypatch.setattr(app, "replay_recorder", recorder)
    monkeypatch.setattr(app, "STATE_DIR", tmp_path)
    store.reset_runtime(task.id)
    rows = read_events(recorder.path(tmp_path, task.id))
    assert rows[-1]["label"] == "task_reset"
    final = project(rows, rows[-1]["sequence"])
    assert final["task"]["status"] == "idle"
    assert final["auto_ml"]["nodes"] == []
    assert final["auto_report"]["report_markdown"] == ""


@pytest.mark.parametrize("deleted", [False, True])
def test_background_capture_ignores_task_changed_during_artifact_read(tmp_path: Path, monkeypatch, deleted: bool):
    task = app.TaskModel.model_validate({**task_data(status="running"), "input_root": str(tmp_path), "output_root": str(tmp_path), "config": {"task_name": "sales", "input_root": str(tmp_path), "output_root": str(tmp_path)}})
    store = SimpleNamespace(_lock=threading.Lock(), _tasks={task.id: task})
    stop = threading.Event()
    captured = []

    def read_snapshot(_task):
        if deleted:
            del store._tasks[task.id]
        else:
            task.updated_at += 1
        stop.set()
        return fixture_snapshot()

    monkeypatch.setattr(app, "store", store)
    monkeypatch.setattr(app, "replay_recorder", SimpleNamespace(capture=lambda *args: captured.append(args)))
    monkeypatch.setattr(app, "_replay_artifact_signature", lambda task: (task.updated_at,))
    monkeypatch.setattr(app, "_local_replay_snapshot", read_snapshot)
    app._record_running_replays(stop)
    assert captured == []


def test_secrets_are_removed_before_persistence_and_delivery(tmp_path: Path):
    key = "sk-" + "testsecret" * 4
    task = task_data(config={"api_key": key})
    snapshot = {"auto_ml": {"nodes": [node_data(code=f'api_key = "{key}"\nprint(1)')], "resolved_config": {"api_key": key}}, "auto_report": {"report_markdown": f"Authorization: Bearer {key}", "resolved_config": {"llm": {"api_key": key}}}}
    recorder = ReplayRecorder()
    recorder.capture(tmp_path, task, snapshot, 200)
    text = recorder.path(tmp_path, task["id"]).read_text(encoding="utf-8")
    assert key not in text
    replay = bundle(task, snapshot, read_events(recorder.path(tmp_path, task["id"])))
    assert key not in json.dumps(replay)
    assert "resolved_config" not in json.dumps(replay)
    assert "config" not in project(replay["events"], len(replay["events"]))["task"]
    assert sanitize({"value": float("nan")}) == {"value": None}


def test_missing_terminal_observation_is_labeled_mixed(tmp_path: Path):
    recorder = ReplayRecorder()
    task = task_data()
    recorder.capture(tmp_path, task_data(status="running", phase="automl"), {"auto_ml": {"pending_nodes": [node_data(status="executing", pending_execution=True, metric=None)]}}, 110)
    replay = bundle(task, fixture_snapshot(), read_events(recorder.path(tmp_path, task["id"])))
    assert replay["fidelity"] == "mixed"
    repaired = [row for row in replay["events"] if row["label"] == "recovered_final_node"]
    assert repaired and all(row["timestamp"] >= 200 for row in repaired)
    final = project(replay["events"], len(replay["events"]))
    assert final["auto_ml"]["best_node_id"] == "n2"
    assert not final["auto_ml"]["pending_nodes"]
    assert final["task"]["status"] == "completed"


def test_interrupted_pending_nodes_are_not_promoted_to_success():
    snapshot = {"auto_ml": {"nodes": [], "pending_nodes": [node_data(status="executing", pending_execution=True, metric=None, finish_time=None)]}}
    replay = bundle(task_data(status="stopped", phase="stopped"), snapshot, [])
    final = project(replay["events"], len(replay["events"]))
    assert not final["auto_ml"]["nodes"]
    assert final["auto_ml"]["pending_nodes"][0]["status"] == "executing"
    assert final["auto_ml"]["best_node_id"] is None


def test_replay_reads_complete_event_stream_without_modifying_task(tmp_path: Path, monkeypatch):
    events_dir = tmp_path / "realize_report"
    events_dir.mkdir()
    path = events_dir / "event_stream.jsonl"
    path.write_text("".join(json.dumps({"ts": 100 + index / 100, "component": "data_cognition", "event": f"event-{index}"}) + "\n" for index in range(550)), encoding="utf-8")
    task = app.TaskModel.model_validate({**task_data(), "input_root": str(tmp_path), "output_root": str(tmp_path), "config": {"task_name": "sales", "input_root": str(tmp_path), "output_root": str(tmp_path)}})
    before = task.model_dump_json()

    class FakeStore:
        def get(self, task_id):
            assert task_id == task.id
            return task

    monkeypatch.setattr(app, "store", FakeStore())
    monkeypatch.setattr(app, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(app, "_build_local_autorealize_snapshot", lambda task: {"report_dir": str(events_dir), "events": []})
    monkeypatch.setattr(app, "_build_local_automl_snapshot", lambda task: {})
    monkeypatch.setattr(app, "_build_local_report_snapshot", lambda task: {})
    monkeypatch.setattr(app, "_json_post", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Replay must not call a service")))
    replay = app.task_replay(task.id)
    assert len([row for row in replay["events"] if row["kind"] == "event"]) == 550
    assert task.model_dump_json() == before
    assert not (tmp_path / "state").exists()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 550


def test_malformed_trailing_append_preserves_history(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"sequence":1}\n{"sequence":', encoding="utf-8")
    assert read_events(path) == [{"sequence": 1}]


def test_terminal_status_keeps_the_last_observed_stage(tmp_path: Path):
    recorder = ReplayRecorder()
    recorder.observe_task(tmp_path, task_data(status="running", phase="report"), 180)
    recorder.observe_task(tmp_path, task_data(), 200)
    rows = read_events(recorder.path(tmp_path, "replay-task"))
    assert rows[-1]["stage"] == "report"


def test_empty_artifacts_do_not_invent_a_replay():
    assert bundle(task_data(), {"auto_realize": {}, "auto_ml": {}, "auto_report": {}}, [])["events"] == []
