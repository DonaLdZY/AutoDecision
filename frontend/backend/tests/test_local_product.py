import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
import pytest

import app
import local_product


@pytest.fixture
def product(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(app, "TASKS_FILE", tmp_path / "state/tasks.json")
    monkeypatch.setattr(app, "store", app.TaskStore())
    monkeypatch.setattr(app.replay_recorder, "observe_task", lambda *args: None)
    source = tmp_path / "input"
    source.mkdir()
    task = app.store.create(app.TaskConfigPayload(task_name="case", input_root=str(source), output_root=str(tmp_path / "runs")))
    monkeypatch.delenv("AUTODECISION_API_TOKEN", raising=False)
    return task, TestClient(app.app)


def test_start_claim_freezes_config_and_rejects_double_submit(product, monkeypatch):
    task, client = product
    calls = []
    monkeypatch.setattr(app.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: calls.append(kw)))
    assert client.post("/api/tasks/start", json={"task_id": task.id}).status_code == 200
    assert task.status == "running" and task.execution_config == task.config.model_dump()
    assert client.post("/api/tasks/start", json={"task_id": task.id}).status_code == 409
    assert len(calls) == 1


def test_new_experiment_preserves_old_files_and_config(product):
    task, client = product
    root = Path(task.output_root) / task.task_name
    root.mkdir(parents=True)
    (root / "proof.txt").write_text("keep me")
    task.run_dir, task.status = str(root), "completed"
    old = task.model_dump()
    response = client.post(f"/api/tasks/{task.id}/experiments")
    assert response.status_code == 200
    child = response.json()
    assert child["id"] != task.id and child["task_name"] != task.task_name
    assert child["parent_task_id"] == task.id and child["experiment_group_id"] == task.id
    assert child["run_dir"] is None and child["execution_config"] is None
    assert task.model_dump() == old and (root / "proof.txt").read_text() == "keep me"
    assert len(client.get(f"/api/tasks/{task.id}/experiments").json()) == 2
    payload = task.config.model_dump()
    payload["input_root"] = "different-input"
    assert client.put(f"/api/tasks/{task.id}", json=payload).status_code == 409
    assert client.put(f"/api/tasks/{child['id']}", json={**child["config"], "input_root": "different-input"}).status_code == 200


def test_start_refuses_existing_directory_without_deleting(product):
    task, client = product
    root = Path(task.output_root) / task.task_name
    root.mkdir(parents=True)
    (root / "proof").write_text("keep")
    assert client.post("/api/tasks/start", json={"task_id": task.id}).status_code == 400
    assert (root / "proof").read_text() == "keep"
    assert task.status == "idle"


def test_resume_claim_keeps_report_checkpoint_and_rejects_double_submit(product, monkeypatch):
    task, client = product
    task.status, task.phase = "failed", "report_failed"
    calls = []
    monkeypatch.setattr(app.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: calls.append(kw)))
    assert client.post("/api/tasks/resume", json={"task_id": task.id}).status_code == 200
    assert task.phase == "resuming"
    assert client.post("/api/tasks/resume", json={"task_id": task.id}).status_code == 409
    reports = []
    monkeypatch.setattr(app, "_rerun_autoreport_thread", lambda tid, checkpoint: reports.append(checkpoint))
    calls[0]["target"]()
    assert reports[0].status == "failed" and reports[0].phase == "report_failed"


def build_solution(task, tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "best_solution"
    root.mkdir(parents=True)
    (root / "model.bin").write_bytes(b"trained-model")
    (root / "solution.py").write_text("def predict(model_path, data): return data")
    (root / "selected_final_solution.py").write_text("# frozen implementation")
    checksum = __import__("hashlib").sha256((root / "selected_final_solution.py").read_bytes()).hexdigest()
    (root / "solution_manifest.json").write_text(json.dumps({"node_id": "winner", "entrypoint": "predict", "artifact_required": True,
        "artifact_path": str(root / "model.bin"), "implementation_path": "selected_final_solution.py", "implementation_file_sha256": checksum}))
    (root / "model_path.txt").write_text(str(root / "model.bin"))
    (root / "runtime/input").mkdir(parents=True)
    (root / "runtime/input/private.csv").write_text("private data")
    (root / "final_evaluation/artifacts").mkdir(parents=True)
    (root / "final_evaluation/artifacts/legacy-model.bin").write_bytes(b"legacy model")
    (root / "final_evaluation/artifacts/final_evaluation.json").write_text(
        '{"holdout_rows":[{"y_true":1.0}]}'
    )
    (root / "final_evaluation/artifacts/holdout_evidence.csv").write_text(
        "sample_id,y_true,y_pred\nprivate-row,1.0,1.1\n"
    )
    (root / "final_evaluation/artifacts/nested").mkdir()
    (root / "final_evaluation/artifacts/nested/holdout_predictions.json").write_text(
        '[{"sample_id":"private-row","y_true":1.0,"y_pred":1.1}]'
    )
    (root / "final_evaluation/result.json").write_text(
        '{"holdout_rows":[{"y_true":1.0}]}'
    )
    (root / "model_artifacts").mkdir()
    (root / "model_artifacts/dev_payloads.json").write_text('[{"target":1.0}]')
    (root / "model_artifacts/holdout_index.json").write_text('[1,2,3]')
    inference_evidence = root / "model_artifacts/working/artifact/evidence"
    inference_evidence.mkdir(parents=True)
    (inference_evidence / "inference_lookup.json").write_text('{"known_value": 2}')
    development_evidence = root / "model_artifacts/working/evidence"
    development_evidence.mkdir(parents=True)
    (development_evidence / "dev_rows.csv").write_text("target\n1\n")
    (root / "config.yaml").write_text("api_key: secret")
    (workspace / "input").mkdir()
    (workspace / "input/description.md").write_text("frozen contract")
    task.auto_ml_workspace_dir = str(workspace)
    task.status = "completed"
    return root


def test_bundle_contains_model_wrapper_frozen_contract_and_relative_paths(product, tmp_path):
    task, client = product
    root = build_solution(task, tmp_path)
    task.execution_config = {
        "input_root": "C:/Users/private/customer-data",
        "output_root": "C:/Users/private/runs",
        "auto_realize": {"task_hint": "customer process requirements"},
    }
    before = (root / "model_path.txt").read_text()
    info = client.get(f"/api/tasks/{task.id}/solution").json()
    assert info["exportable"] and info["node_id"] == "winner"
    response = client.get(f"/api/tasks/{task.id}/solution/bundle")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert {"solution.py", "selected_final_solution.py", "model.bin", "package_inventory.json", "contract/description.md",
                "final_evaluation/artifacts/legacy-model.bin"} <= set(archive.namelist())
        assert archive.read("contract/description.md") == b"frozen contract"
        assert archive.read("model_path.txt") == b"model.bin\n"
        assert json.loads(archive.read("solution_manifest.json"))["artifact_path"] == "model.bin"
        inventory = json.loads(archive.read("package_inventory.json"))
        assert inventory["schema_version"] == "autodecision.solution_export.v1"
        assert "source_config" not in inventory
        assert "customer process requirements" not in archive.read("package_inventory.json").decode()
        assert "C:/Users/private" not in archive.read("package_inventory.json").decode()
        assert "runtime/input/private.csv" not in archive.namelist()
        assert "config.yaml" not in archive.namelist()
        assert "final_evaluation/result.json" not in archive.namelist()
        assert "final_evaluation/artifacts/final_evaluation.json" not in archive.namelist()
        assert "final_evaluation/artifacts/holdout_evidence.csv" not in archive.namelist()
        assert "final_evaluation/artifacts/nested/holdout_predictions.json" not in archive.namelist()
        assert "model_artifacts/dev_payloads.json" not in archive.namelist()
        assert "model_artifacts/holdout_index.json" not in archive.namelist()
        assert "model_artifacts/working/artifact/evidence/inference_lookup.json" in archive.namelist()
        assert "model_artifacts/working/evidence/dev_rows.csv" not in archive.namelist()
    assert (root / "model_path.txt").read_text() == before


@pytest.mark.parametrize("problem", ["missing", "external", "tampered", "running"])
def test_bundle_rejects_incomplete_or_changing_delivery(product, tmp_path, problem):
    task, client = product
    root = build_solution(task, tmp_path)
    if problem == "missing": (root / "model.bin").unlink()
    if problem == "external": (root / "model_path.txt").write_text(str(tmp_path / "outside.bin"))
    if problem == "tampered": (root / "selected_final_solution.py").write_text("changed")
    if problem == "running": task.status, task.run_started_at = "running", app.now_ts()
    assert client.get(f"/api/tasks/{task.id}/solution/bundle").status_code == 409


def test_embedding_stays_optional_and_images_use_analysis_role():
    library, roles = app._normalize_model_library({}, {"modelLibrary": [{"id": "chat", "model": "text-model"}], "roleModels": {}}, {})
    assert roles["autoMlCode"] == "chat"
    assert roles["embedding"] == ""
    assert 'autoRealizeVision' not in roles
    assert app._selected_model({"modelLibrary": library, "roleModels": roles, "vllm": {"model": "legacy"}}, "autoRealizeVision")['id'] == 'chat'


def test_image_probe_checks_image_payload_without_sending_user_files(product, monkeypatch):
    task, client = product
    model = {'id':'analysis', 'model':'multimodal', 'baseUrl':'http://localhost:9000/v1', 'apiKey':'probe-secret'}
    settings = app.GlobalSettingsModel(llm={'modelLibrary':[model], 'roleModels':{'autoRealize':'analysis'}})
    monkeypatch.setattr(app, 'get_global_settings', lambda: settings)
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"choices":[{"message":{"content":"red"}}]}'
    def request(req, **kwargs):
        assert req.get_header("User-agent") == "AutoDecision"
        seen.append(json.loads(req.data))
        return Response()
    monkeypatch.setattr(local_product.urllib.request, 'urlopen', request)
    result = client.post('/api/system/probe-model', json={'role':'autoRealize','capability':'image'})
    assert result.status_code == 200 and result.json()['capability'] == 'image_request_only'
    content = seen[0]['messages'][0]['content']
    assert content[1]['type'] == 'image_url' and content[1]['image_url']['url'].startswith('data:image/png;base64,')
    assert seen[0]['model'] == 'multimodal'
    saved = (app.STATE_DIR/'model_checks.json').read_text()
    assert 'probe-secret' not in saved and 'data:image' not in saved
    assert json.loads(saved)['autoRealize']['capability'] == 'image_request_only'
    def reject(req, **kwargs): raise ValueError('provider body contains probe-secret')
    monkeypatch.setattr(local_product.urllib.request, 'urlopen', reject)
    model['model'] = 'text-only'
    failed = client.post('/api/system/probe-model', json={'role':'autoRealize','capability':'image'})
    assert failed.status_code == 400 and '图片输入' in failed.json()['detail']
    assert 'probe-secret' not in failed.text


def test_readiness_is_read_only_and_model_probe_records_only_hash(product, monkeypatch, tmp_path):
    task, client = product
    model = {"id": "local", "model": "demo", "baseUrl": "http://127.0.0.1:9000/v1", "apiKey": "private-secret"}
    settings = app.GlobalSettingsModel(python={"executable": "python"}, llm={"modelLibrary": [model], "roleModels": {r: "local" for r in ["autoRealize", "autoMlCode", "autoMlFeedback"]}})
    monkeypatch.setattr(app, "get_global_settings", lambda: settings)
    monkeypatch.setattr(local_product.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps({"version": [3, 12, 13], "missing": []}), returncode=0))
    seen = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"choices":[{"message":{"content":"The image is red."}}]}'
    def request(req, **kwargs):
        seen.append(req)
        return Response()
    monkeypatch.setattr(local_product.urllib.request, "urlopen", request)
    response = client.get(f"/api/system/readiness?task_id={task.id}")
    assert response.status_code == 200 and not response.json()["ready"]
    analysis_check = next(c for c in response.json()["checks"] if c["key"] == "autoRealize")
    assert analysis_check['status'] == 'fail' and '多模态' in analysis_check['detail']
    assert all(isinstance(req, str) and req.endswith("/health") for req in seen)
    assert "private-secret" not in response.text
    assert not (app.STATE_DIR / "model_checks.json").exists()
    assert client.post("/api/system/probe-model", json={"role":"autoRealize", "capability":"image"}).status_code == 200
    assert client.post("/api/system/probe-model", json={"role": "autoMlCode"}).status_code == 200
    assert "private-secret" not in (app.STATE_DIR / "model_checks.json").read_text()
    row = next(c for c in client.get("/api/system/readiness").json()["checks"] if c["key"] == "autoMlCode")
    assert row["status"] == "pass"
    assert client.get(f"/api/system/readiness?task_id={task.id}").json()['ready'] is True
    model["model"] = "changed"
    row = next(c for c in client.get("/api/system/readiness").json()["checks"] if c["key"] == "autoMlCode")
    assert row["status"] == "warn"


def test_trial_calls_predict_in_separate_process_and_preserves_original(product, tmp_path, monkeypatch):
    task, client = product
    root = build_solution(task, tmp_path)
    (root / "solution.py").write_text("def predict(model_path, data):\n    return {'answer': data['value'] * 2}\ndef train(*args):\n    raise RuntimeError('train must not be called')\n")
    monkeypatch.setattr(app, "get_global_settings", lambda: app.GlobalSettingsModel(python={"executable": app.sys.executable}))
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    response = client.post(f"/api/tasks/{task.id}/solution/trial", json={"data_json": '{"value": 7}'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["result"] == {"answer": 14} and result["entrypoint"] == "predict"
    assert len(result["input_sha256"]) == 64 and result["node_id"] == "winner"
    assert (app.STATE_DIR / "trials" / task.id / (result["trial_id"] + ".json")).is_file()
    history = client.get(f"/api/tasks/{task.id}/solution/trials").json()
    assert history[0]["trial_id"] == result["trial_id"] and "result" not in history[0]
    assert client.get(f"/api/tasks/{task.id}/solution/trials/{result['trial_id']}").json()["result"] == {"answer": 14}
    assert client.get(f"/api/tasks/{task.id}/solution/trials/invalid").status_code == 400
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_optional_manifest_artifact_path_is_used_for_trial_and_bundle(product, tmp_path, monkeypatch):
    task, client = product
    root = build_solution(task, tmp_path)
    manifest = json.loads((root / "solution_manifest.json").read_text())
    manifest.update(artifact_required=False, artifact_path="model.bin")
    (root / "solution_manifest.json").write_text(json.dumps(manifest))
    (root / "model_path.txt").unlink()
    (root / "solution.py").write_text(
        "from pathlib import Path\n"
        "def predict(model_path, data):\n"
        "    assert Path(model_path).name == 'model.bin'\n"
        "    return {'answer': data['value'] * 2}\n"
    )
    monkeypatch.setattr(app, "get_global_settings", lambda: app.GlobalSettingsModel(python={"executable": app.sys.executable}))

    info = client.get(f"/api/tasks/{task.id}/solution").json()
    assert info["trial_ready"] and info["model_path"] == "model.bin"
    trial = client.post(f"/api/tasks/{task.id}/solution/trial", json={"data_json": '{"value": 7}'})
    assert trial.status_code == 200, trial.text
    assert trial.json()["result"] == {"answer": 14}

    response = client.get(f"/api/tasks/{task.id}/solution/bundle")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read("model_path.txt") == b"model.bin\n"
        exported = json.loads(archive.read("solution_manifest.json"))
        assert exported["artifact_path"] == "model.bin"


def test_trial_timeout_and_csv_path_restriction(product, tmp_path, monkeypatch):
    task, client = product
    root = build_solution(task, tmp_path)
    (root / "solution.py").write_text("import time\ndef predict(model_path, data):\n    time.sleep(30)\n")
    monkeypatch.setattr(app, "get_global_settings", lambda: app.GlobalSettingsModel(python={"executable": app.sys.executable}))
    response = client.post(f"/api/tasks/{task.id}/solution/trial", json={"data_json": '{}', "timeout_seconds": 1})
    assert response.status_code == 408
    assert local_product.TRIAL_LOCK.acquire(blocking=False)
    local_product.TRIAL_LOCK.release()
    outside = tmp_path / "outside.csv"
    outside.write_text("a\n1\n")
    response = client.post(f"/api/tasks/{task.id}/solution/trial", json={"input_mode": "csv", "csv_path": str(outside)})
    assert response.status_code == 400


def test_csv_trial_uses_dataframe_and_serializes_records(product, tmp_path, monkeypatch):
    task, client = product
    root = build_solution(task, tmp_path)
    (root / "solution.py").write_text("def predict(model_path, data):\n    return data.assign(prediction=data['value'] * 2)\n")
    source = Path(task.input_root) / "trial.csv"
    source.write_text("value\n7\n9\n")
    monkeypatch.setattr(app, "get_global_settings", lambda: app.GlobalSettingsModel(python={"executable": app.sys.executable}))
    response = client.post(f"/api/tasks/{task.id}/solution/trial", json={"input_mode": "csv", "csv_path": str(source)})
    assert response.status_code == 200, response.text
    assert response.json()["result"] == [{"value": 7, "prediction": 14}, {"value": 9, "prediction": 18}]


def test_release_versions_agree():
    assert (app.APP_ROOT / "VERSION").read_text().strip() == json.loads((app.APP_ROOT / "frontend/ui/package.json").read_text())["version"]
