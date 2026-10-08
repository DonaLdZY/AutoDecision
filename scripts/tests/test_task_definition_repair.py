import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("task_repair", Path(__file__).parents[1] / "repair-industrial-task-definition.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


def setup_repair(tmp_path, monkeypatch):
    task = {"run_dir": str(tmp_path / "tasks/steel"), "status": "completed", "phase": "autorealize_completed"}
    source = Path(task["run_dir"]) / "autorealize"
    candidate = tmp_path / "stage-repairs/revision/autorealize"
    contract = {"passed": True, "executable": True, "primary_metric": "MAE"}
    for root in (source, candidate):
        report = root / "realize_report"
        report.mkdir(parents=True)
        (root / "description.md").write_text("old" if root == source else "repaired")
        (report / "automl_context.md").write_text("full context")
        (report / "evaluation_contract_report.json").write_text(json.dumps({"final": contract}))
        (report / "main_task_protocol.json").write_text(json.dumps({"evaluation_contract": contract}))
        (report / "automl_context_pack.json").write_text(json.dumps({
            "evaluation_contract": contract, "execution_contract": {"readiness": "ready"},
        }))
        (report / "artifact_consistency_report.json").write_text('{"final":{"passed":true}}')
        (report / "task_definition_report.json").write_text(json.dumps({
            "evaluation_contract": contract, "defects_after_gate": [],
            "downstream_context": {"evaluation_contract": contract},
        }))
    (source / "data.csv").write_text("original data")
    result_file = candidate.parent / "result.json"
    result_file.write_text(json.dumps({
        "slug": "steel", "passed": True, "source": str(source), "candidate": str(candidate),
        "source_fingerprint": repair.stages.fingerprint(repair.stages.stage_artifacts(task, "autorealize")),
        "candidate_fingerprint": repair.stages.fingerprint(repair.stages.stage_artifacts({"run_dir": str(candidate.parent)}, "autorealize")),
    }))
    monkeypatch.setattr(repair.stages.batch, "OUT", tmp_path)
    monkeypatch.setattr(repair.stages, "LEDGER", tmp_path / "stage-reviews.json")
    monkeypatch.setattr(repair.stages, "current_task", lambda slug: task)
    return source, candidate, result_file


@pytest.mark.parametrize("changed", ["source", "candidate"])
def test_apply_rejects_changed_snapshot_before_copying(tmp_path, monkeypatch, changed):
    source, candidate, result = setup_repair(tmp_path, monkeypatch)
    ((source if changed == "source" else candidate) / "description.md").write_text("unreviewed")
    with pytest.raises(RuntimeError, match="changed"):
        repair.apply_repair(result)
    assert (source / "description.md").read_text() != "repaired"
    assert not (tmp_path / "stage-archives").exists()


def test_apply_archives_original_and_preserves_input_data(tmp_path, monkeypatch):
    source, candidate, result_file = setup_repair(tmp_path, monkeypatch)
    (source / "sample_submission.csv").write_text("old_id,old_prediction\n")
    (candidate / "sample_submission.csv").write_text("request_id,prediction\n")
    repair.apply_repair(result_file)
    result = json.loads(result_file.read_text())
    assert (source / "description.md").read_text() == "repaired"
    assert (source / "data.csv").read_text() == "original data"
    assert (Path(result["archive"]) / "description.md").read_text() == "old"
    assert (candidate / "description.md").read_text() == "repaired"
    assert (source / "sample_submission.csv").read_text() == "request_id,prediction\n"
    assert (Path(result["archive"]) / "sample_submission.csv").read_text() == "old_id,old_prediction\n"


def test_replay_uses_saved_provider_patch_and_rejects_known_bad_references(tmp_path):
    from types import SimpleNamespace

    entry = {"round": 2, "patch": {"revised_sections": {"## Title": "## Title\nNew"}},
             "patch_missing_file_references": [], "candidate_new_deterministic_defects": []}
    report = tmp_path / "artifact_consistency_report.json"
    report.write_text(json.dumps({"rounds": [entry, {"round": 3, "review": {"passed": False}}]}))
    module = SimpleNamespace(_replace_h2_section=lambda desc, title, replacement: replacement)
    desc, audit = repair.reapply_last_patch(module, "## Title\nOld", tmp_path)
    assert desc == "## Title\nNew"
    assert audit["source_round"] == 2
    entry["patch_missing_file_references"] = ["invented.csv"]
    report.write_text(json.dumps({"rounds": [entry]}))
    with pytest.raises(RuntimeError, match="failed safety checks"):
        repair.reapply_last_patch(module, "Original", tmp_path)


def test_restore_original_provider_source_mapping_without_changing_contract(tmp_path):
    from autorealize.models import SampleSubmissionSpec
    spec = SampleSubmissionSpec(columns=["probability"], source="generated_spec",
                                source_fields={"probability": "data.csv::Process temperature [K] temperature [K]"},
                                validation_rules=["Do not fit on holdout"])
    original = {"sample_submission_spec": {"columns": spec.columns, "source": spec.source,
                "source_fields": {"probability": "data.csv::Process temperature [K]"}}}
    cache = tmp_path / "llm_cache.jsonl"
    cache.write_text(json.dumps({"key": "paid-response", "response": json.dumps(original)}), encoding="utf-8")
    receipt = repair.restore_sample_sources(tmp_path, spec)
    assert receipt["cache_key"] == "paid-response"
    assert spec.source_fields == original["sample_submission_spec"]["source_fields"]
    assert spec.validation_rules == ["Do not fit on holdout"]


@pytest.mark.parametrize("changed", ["contract", "evidence", "cognition", "requirements"])
def test_reviewed_evaluator_reuse_rejects_changed_evidence(tmp_path, changed):
    contract = tmp_path / "contract.json"
    evidence = tmp_path / "frozen-evidence.json"
    review = tmp_path / "review.json"
    cognition = {"task_hint": "Predict target"}
    contract.write_text('{"passed":true}', encoding="utf-8")
    evidence.write_text(json.dumps({**cognition, "original_requirements_full": "Original"}), encoding="utf-8")
    review.write_text(json.dumps({"passed": True,
        "accepted_contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
        "frozen_evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}), encoding="utf-8")
    original = "Original"
    if changed == "contract":
        contract.write_text('{"passed":false}', encoding="utf-8")
    elif changed == "evidence":
        evidence.write_text('{}', encoding="utf-8")
    elif changed == "cognition":
        cognition["task_hint"] = "Different task"
    else:
        original = "Different requirements"
    with pytest.raises(RuntimeError, match="changed|no longer matches"):
        repair.load_reviewed_evaluation(contract, review, cognition, original)


@pytest.mark.parametrize("changed", [None, "task", "hint", "source"])
def test_recovery_context_preserves_current_request_and_verified_sources(tmp_path, changed):
    source = tmp_path / "independent-review.json"
    source.write_text('{"capacity_dates_missing":51}', encoding="utf-8")
    task = {"id": "delivery", "config": {"auto_realize": {"task_hint": "Latest coverage first request"}}}
    value = {"schema": "industrial.recovery_context.v1", "task_id": task["id"],
             "task_hint": task["config"]["auto_realize"]["task_hint"],
             "retained_user_requirements": ["Deliver the reusable model and data gap report"],
             "evidence_files": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}}
    path = tmp_path / "context.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    if changed == "task":
        task["id"] = "different-task"
    elif changed == "hint":
        task["config"]["auto_realize"]["task_hint"] = "User changed requirements"
    elif changed == "source":
        source.write_text('{"capacity_dates_missing":0}', encoding="utf-8")
    if changed:
        with pytest.raises(RuntimeError, match="does not match|changed"):
            repair.load_recovery_context(path, task)
    else:
        assert repair.load_recovery_context(path, task) == value
        assert task["config"]["auto_realize"]["task_hint"] == value["task_hint"]


@pytest.mark.parametrize("changed", [None, "hash", "destination", "name"])
def test_synthetic_install_checks_all_inputs_without_replacing_original_data(tmp_path, changed):
    source, data = tmp_path / "fixture", tmp_path / "data"
    source.mkdir()
    data.mkdir()
    original = data / "orders.csv"
    original.write_text("Original data")
    fixture = source / "test.json"
    fixture.write_text('{"synthetic":true}')
    row = {"name": fixture.name, "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()}
    context = {"implementation_validation": {"fixture_source_directory": str(source), "fixture_manifest": [row]}}
    destination = data / "internal_validation/synthetic_delivery/test.json"
    if changed == "hash":
        row["sha256"] = "invalid"
    elif changed == "destination":
        destination.parent.mkdir(parents=True)
        destination.write_text("Other task input")
    elif changed == "name":
        row["name"] = "../test.json"
    if changed:
        with pytest.raises(RuntimeError):
            repair.install_recovery_fixtures(context, data)
        assert not destination.exists() or destination.read_text() == "Other task input"
    else:
        assert repair.install_recovery_fixtures(context, data) == [str(destination)]
        assert destination.read_bytes() == fixture.read_bytes()
    assert original.read_text() == "Original data"
