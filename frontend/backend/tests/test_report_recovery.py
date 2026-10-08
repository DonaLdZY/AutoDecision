import json

import pytest

from report_recovery import REPORT_FILES, config_digest, file_digest, validate_report_recovery


def fixture_report(tmp_path):
    root = tmp_path / "task"
    report = root / "report"
    report.mkdir(parents=True)
    logs = root / "automl/logs"
    logs.mkdir(parents=True)
    cognition = root / "autorealize/realize_report"
    cognition.mkdir(parents=True)
    files = [logs / name for name in ("run_status.json", "search_state.json", "journal.json")]
    files += [cognition.parent / "description.md", cognition / "automl_context_pack.json"]
    for path in files:
        path.write_text("{}")
    (logs / "run_status.json").write_text('{"status":"completed"}')
    article = "# Report\n\n## Results\nVerified results."
    (report / "report.md").write_text(article)
    (report / "report.json").write_text(json.dumps({"article_markdown": article}))
    (report / "report_trace.json").write_text(json.dumps({"audit": {"status": "pass", "complete_draft_covered": True}}))
    independent = report / "independent-review.json"
    independent.write_text('{"passed":true}')
    task = {"id": "task", "run_dir": str(root), "input_root": str(tmp_path / "input"),
            "phase": "report_failed", "status": "failed", "config": {"task_hint": "current"},
            "auto_ml_log_dir": str(logs)}
    receipt = {"passed": True, "task_id": task["id"], "task_config_sha256": config_digest(task["config"]),
               "report_sha256": {name: file_digest(report / name) for name in REPORT_FILES},
               "evidence_sha256": {str(path.resolve()): file_digest(path) for path in files},
               "independent_review": {"path": str(independent), "sha256": file_digest(independent)}}
    (report / "recovery-review.json").write_text(json.dumps(receipt))
    return task, report, receipt


def test_recovers_matching_complete_report_and_rejects_changed_source(tmp_path):
    task, report, receipt = fixture_report(tmp_path)
    assert validate_report_recovery(task, report) == receipt
    (report.parent / "autorealize/description.md").write_text("Changed task constraints")
    with pytest.raises(ValueError, match="evidence changed"):
        validate_report_recovery(task, report)


@pytest.mark.parametrize("mutation", ["task", "running", "config", "report", "audit", "omitted_source", "unpassed", "mismatch"])
def test_recovery_rejects_stale_or_unverified_artifacts(tmp_path, mutation):
    task, report, receipt = fixture_report(tmp_path)
    if mutation == "task":
        receipt["task_id"] = "other"
    elif mutation == "running":
        task["status"] = "running"
    elif mutation == "config":
        task["config"]["task_hint"] = "New requirements"
    elif mutation == "report":
        (report / "report.md").write_text("Changed report")
    elif mutation == "audit":
        (report / "report_trace.json").write_text('{"audit":{"status":"pass","complete_draft_covered":false}}')
        receipt["report_sha256"]["report_trace.json"] = file_digest(report / "report_trace.json")
    elif mutation == "omitted_source":
        receipt["evidence_sha256"].clear()
    elif mutation == "unpassed":
        (report / "independent-review.json").write_text('{"passed":false}')
        receipt["independent_review"]["sha256"] = file_digest(report / "independent-review.json")
    else:
        (report / "report.json").write_text('{"article_markdown":"Different article"}')
        receipt["report_sha256"]["report.json"] = file_digest(report / "report.json")
    (report / "recovery-review.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        validate_report_recovery(task, report)


def test_recovery_rejects_external_evidence(tmp_path):
    task, report, receipt = fixture_report(tmp_path)
    external = tmp_path / "outside.txt"
    external.write_text("External content")
    receipt["evidence_sha256"][str(external)] = file_digest(external)
    (report / "recovery-review.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="outside"):
        validate_report_recovery(task, report)
