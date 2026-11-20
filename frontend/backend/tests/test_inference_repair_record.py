"""Repair receipts must stay bound to their source/model and never replace frozen evaluation."""
import hashlib
import json
from types import SimpleNamespace
import pytest
import delivery


def test_repair_evidence_is_bound_and_separate(tmp_path):
    root = tmp_path / "best_solution"
    root.mkdir()
    source, model = b"def predict(model_path, data): return data\n", b"fixed-model"
    (root / "implementation.py").write_bytes(source)
    (root / "model.bin").write_bytes(model)
    (root / "model_path.txt").write_text("model.bin")
    source_hash, model_hash = hashlib.sha256(source).hexdigest(), hashlib.sha256(model).hexdigest()
    revision = {"source_sha256":source_hash,"parent_frozen_source_sha256":"original-source",
        "provenance":"repair.json","validation":"validation.json"}
    manifest = {"implementation_path":"implementation.py","inference_revision":revision}
    provenance = {"repaired_model_sha256":model_hash}
    metrics = {"WAPE":0.17,"n":3643}
    validation = {"status":"passed","source_sha256":source_hash,"model_sha256":model_hash,"metrics":metrics}
    evaluation = {"status":"completed","metrics":metrics}
    def write(name, value): (root / name).write_text(json.dumps(value),encoding="utf-8")
    write("solution_manifest.json",manifest);write("repair.json",provenance)
    write("validation.json",validation);write("inference_repair_evaluation.json",evaluation)
    g = SimpleNamespace(safe_read_json=lambda path, default: json.loads(path.read_text()) if path.exists() else default)
    original = {"status":"completed","executed_code_sha256":"original-source","independent_verification":"pending"}
    result = delivery.inference_repair_record(g,tmp_path,original)
    assert result["status"] == "recorded" and result["prior_holdout_exposure"] is True
    assert result["metrics"] == metrics
    assert original == {"status":"completed","executed_code_sha256":"original-source","independent_verification":"pending"}
    for name, content in [("implementation.py",b"changed"),("model.bin",b"changed")]:
        path = root / name; saved=path.read_bytes();path.write_bytes(content)
        assert delivery.inference_repair_record(g,tmp_path,original)["status"] == "unavailable"
        path.write_bytes(saved)
    evaluation["metrics"] = {"WAPE":float("nan")}
    write("inference_repair_evaluation.json",evaluation)
    assert delivery.inference_repair_record(g,tmp_path,original)["status"] == "unavailable"
    evaluation["metrics"]=metrics;write("inference_repair_evaluation.json",evaluation)
    assert delivery.inference_repair_record(g,tmp_path,{**original,"executed_code_sha256":"other"})["status"] == "unavailable"
    manifest["implementation_path"]="../outside.py";write("solution_manifest.json",manifest)
    assert delivery.inference_repair_record(g,tmp_path,original)["status"] == "unavailable"


def test_absent_repair_does_not_change_legacy_evaluation(tmp_path):
    g = SimpleNamespace(safe_read_json=lambda *_: {})
    assert delivery.inference_repair_record(g,tmp_path,{"status":"completed"}) is None
