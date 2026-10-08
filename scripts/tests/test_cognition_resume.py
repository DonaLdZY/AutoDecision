import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("cognition_resume", Path(__file__).parents[1] / "recompile-industrial-task-definition.py")
resume = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resume)


def checkpoint(tmp_path):
    source, original = tmp_path / "run", tmp_path / "original"
    (source / "realize_report").mkdir(parents=True)
    (source / "data").mkdir()
    original.mkdir()
    for root in (source / "data", original):
        (root / "capacity.csv").write_text("date,vehicles\n,12\n")
    raw = {"task_hint": "Do not invent capacity dates", "files": [{"path": "capacity.csv"}],
           "relations": [], "summary": {"file_count": 1, "relation_count": 0},
           "question_investigation": {"answers": ["Dates are missing"]},
           "constraint_memory": {"items": ["No assumed dates"]}}
    (source / "realize_report/data_cognition_report.json").write_text(json.dumps(raw))
    return source, original, raw


def test_reuse_preserves_constraints_and_probe_answers(tmp_path):
    source, original, raw = checkpoint(tmp_path)
    actual, root, hashes = resume.load_completed_cognition(source, original, raw["task_hint"])
    assert actual == raw
    assert root == source / "data"
    assert set(hashes) == {"capacity.csv"}


def test_recovery_removes_generated_sample_that_was_not_an_original_input(tmp_path):
    copied, original = tmp_path / "copied", tmp_path / "original"
    copied.mkdir()
    original.mkdir()
    (copied / "sample_submission.csv").write_text("generated\n")
    assert resume.remove_generated_input_artifacts(copied, original) == ["sample_submission.csv"]
    assert not (copied / "sample_submission.csv").exists()

    (copied / "sample_submission.csv").write_text("official\n")
    (original / "sample_submission.csv").write_text("official\n")
    assert resume.remove_generated_input_artifacts(copied, original) == []
    assert (copied / "sample_submission.csv").is_file()


@pytest.mark.parametrize("change", ["data", "hint", "incomplete", "external_reference"])
def test_changed_or_incomplete_checkpoint_is_rejected(tmp_path, change):
    source, original, raw = checkpoint(tmp_path)
    hint = raw["task_hint"]
    if change == "data":
        (original / "capacity.csv").write_text("date,vehicles\n2026-09-08,12\n")
    elif change == "hint":
        hint = "Assume dates"
    elif change == "incomplete":
        raw["summary"]["file_count"] = 2
    else:
        raw["files"][0]["path"] = "../../original/capacity.csv"
    (source / "realize_report/data_cognition_report.json").write_text(json.dumps(raw))
    with pytest.raises(RuntimeError):
        resume.load_completed_cognition(source, original, hint)


@pytest.mark.parametrize("phase", ["autorealize_failed", "stopped", "prepare_automl_input_failed"])
def test_failed_service_does_not_count_as_recovered_without_receipt(tmp_path, phase):
    task = {"run_dir": str(tmp_path), "phase": phase, "status": "failed"}
    assert not resume.stages.recovered_task_definition_completed(task)


@pytest.mark.parametrize("phase", ["autorealize_failed", "stopped", "prepare_automl_input_failed"])
def test_recovery_receipt_requires_current_audited_artifacts(tmp_path, monkeypatch, phase):
    task = {"run_dir": str(tmp_path), "phase": phase, "status": "failed"}
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"constraint":"preserved"}')
    monkeypatch.setattr(resume.stages, "stage_artifacts", lambda *_: [artifact])
    monkeypatch.setattr(resume.stages, "verify_task_definition", lambda _: None)
    receipt = {"passed": True, "artifact_fingerprint": resume.stages.fingerprint([artifact])}
    (tmp_path / "task-definition-recovery.json").write_text(json.dumps(receipt))
    assert resume.stages.recovered_task_definition_completed(task)
    artifact.write_text('{"constraint":"removed"}')
    assert not resume.stages.recovered_task_definition_completed(task)
