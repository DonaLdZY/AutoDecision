"""Bounded integration smoke using an explicitly configured OpenAI-compatible API.

Requires AUTODECISION_TEST_API_KEY, AUTODECISION_TEST_BASE_URL, and running services.
The generated summary contains no credentials. Test data is the public quickstart.
"""

from __future__ import annotations

import argparse
import base64
import io
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def request(base: str, path: str, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def provider_smoke(base_url: str, api_key: str):
    from openai import OpenAI
    from PIL import Image, ImageDraw

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=120, max_retries=0)
    image = Image.new("RGB", (320, 120), "white")
    ImageDraw.Draw(image).text((30, 25), "READY", fill="black", font_size=48)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    visual_input = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    probes = [
        ("text", "gpt-5.6-sol", [{"role": "user", "content": "Reply with exactly READY."}], {}),
        ("json", "gpt-5.6-sol", [{"role": "user", "content": 'Return a JSON object with key "status" and string value "ready".'}], {"response_format": {"type": "json_object"}}),
        ("vision", "glm-5.3-flash", [{"role": "user", "content": [
            {"type": "text", "text": "Read the uppercase word in this image. Return the word only."},
            {"type": "image_url", "image_url": {"url": visual_input}},
        ]}], {}),
    ]
    results = []
    for name, model, messages, options in probes:
        started = time.monotonic()
        try:
            response = client.chat.completions.create(model=model, messages=messages, max_tokens=256, **options)
            text = response.choices[0].message.content or ""
            passed = json.loads(text).get("status") == "ready" if name == "json" else "READY" in text.upper()
            row = {"probe": name, "model": model, "passed": passed, "response": text[:1000],
                   "seconds": round(time.monotonic() - started, 2),
                   "usage": response.usage.model_dump() if response.usage else {}}
        except Exception as exc:
            row = {"probe": name, "model": model, "passed": False,
                   "error": str(exc).replace(api_key, "[REDACTED]")[:1000],
                   "seconds": round(time.monotonic() - started, 2)}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return results


def submit(args):
    if (args.output / "task.json").exists():
        raise RuntimeError("A validation task is already recorded here; use status or a new --output directory.")
    api_key = os.environ["AUTODECISION_TEST_API_KEY"]
    base_url = os.environ["AUTODECISION_TEST_BASE_URL"]
    probes = provider_smoke(base_url, api_key)
    save(args.output / "provider-smoke.json", probes)
    if not all(row["passed"] for row in probes if row["probe"] != "vision"):
        raise RuntimeError("Text/JSON provider smoke failed; task was not submitted.")
    settings = request(args.gateway, "/api/settings/global")
    model = {"id": "validation-text", "name": "Validation text", "model": "gpt-5.6-sol",
             "baseUrl": base_url, "apiKey": api_key, "thinkingMode": "default",
             "reasoningEffort": "default", "maxTokens": 32768, "contextWindowTokens": 131072}
    vision = {**model, "id": "validation-vision", "name": "Validation vision", "model": "glm-5.3-flash"}
    settings["python"] = {"executable": sys.executable}
    settings["llm"] = {"modelLibrary": [model, vision], "roleModels": {
        "autoRealize": model["id"], "autoMlCode": model["id"], "autoMlFeedback": model["id"],
        "autoRealizeVision": vision["id"], "embedding": "",
    }, "vllm": {"enabled": True}}
    req = urllib.request.Request(args.gateway + "/api/settings/global",
                                 data=json.dumps(settings).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as response:
        json.load(response)
    input_root = args.output / "input"
    shutil.copytree(ROOT / "examples" / "quickstart" / "input", input_root, dirs_exist_ok=True)
    (input_root / "validation_protocol.md").write_text(
        "# Validation and Delivery Protocol\n\n"
        "This is a synthetic integration demonstration, not a real sales forecast.\n"
        "Use all rows with day_index <= 10 for fitting and all rows with day_index >= 11 "
        "from train.csv as the fixed validation set. Report MAE over those validation rows.\n"
        "All candidates and any ensemble must use this same split and evaluator. "
        "Use only store_id, day_index, promotion and weekday as predictors; row_id is output identity only.\n"
        "Fit preprocessing only on training rows. After evaluation, refit the selected model on train.csv "
        "and predict the provided predict.csv rows. Predict.csv and sample_submission.csv contain no labels.\n"
        "Deliver reusable training and inference code with a saved preprocessing/model artifact and dependencies. "
        "A fresh Python process must load the artifact and write exactly row_id,sales without retraining.\n"
        "For this bounded test, use installed numpy, pandas, scikit-learn and joblib on CPU. "
        "No external datasets, pretrained downloads or package installations are needed.\n",
        encoding="utf-8",
    )
    payload = {
        "task_name": "Live validation - store sales", "input_root": str(input_root),
        "output_root": str(args.output / "task-runs"), "output_language": "zh",
        "auto_realize": {"task_hint": "Predict store sales for the supplied future rows and deliver a reusable model, following all source requirements.",
            "enable_vllm": False, "llm_concurrency": 1, "llm_timeout": 180,
            "llm_file_cognition_mode": "documents_only", "enable_question_investigator": True,
            "investigation_max_questions": 2, "investigation_max_rounds_per_question": 1,
            "investigation_max_scripts_per_question": 1, "artifact_consistency_max_rounds": 1},
        "auto_ml": {"steps": 4, "time_limit_secs": 1800, "parallel_search_num": 1,
            "initial_drafts": 2, "search_num_drafts": 2, "search_num_improves": 1,
            "use_global_memory": False, "use_coldstart": False, "use_diff_mode": False,
            "use_stepwise_after_first": False, "auto_install_missing_dependencies": False,
            "exec_timeout_secs": 90, "code_request_timeout_secs": 240, "feedback_request_timeout_secs": 180,
            "code_generation_max_retries": 1, "feedback_generation_max_retries": 1,
            "code_continuation_max_rounds": 0, "feedback_continuation_max_rounds": 0,
            "code_review_max_attempts": 1, "preflight_regeneration_max_attempts": 1,
            "result_review_max_attempts": 1, "refine_plan_max_attempts": 1,
            "code_generation_extract_max_attempts": 1, "metric_direction_max_attempts": 1,
            "code_review_escalate_to_code": False, "result_adjudicator_on_anomaly": False,
            "fusion_vs_evolution_prob": 1.0, "branch_fusion_trigger_prob": 1.0,
            "search_fusion_min_remaining_seconds": 60, "search_fusion_min_successful_nodes": 2,
            "search_fusion_min_branches": 2, "search_branch_stagnation_threshold": 1,
            "use_optimization_experience_library": False},
        "auto_report": {"enabled": True, "detail_level": "concise", "comparison_candidate_limit": 3,
                        "max_retrieval_rounds": 0, "enable_report_audit": True},
        "resources": {"cpu_cores": 2, "memory_limit_gb": 8, "accelerator_mode": "none"},
    }
    task = request(args.gateway, "/api/tasks", payload)
    save(args.output / "task.json", task)
    request(args.gateway, "/api/tasks/start", {"task_id": task["id"]})
    print(json.dumps({"task_id": task["id"], "status": "submitted", "gateway": args.gateway}), flush=True)


def status(args):
    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    tasks = request(args.gateway, "/api/tasks")
    current = next(item for item in tasks if item["id"] == task["id"])
    snapshot = request(args.gateway, f"/api/tasks/{task['id']}/snapshot")
    save(args.output / "latest-task.json", current)
    save(args.output / "latest-snapshot.json", snapshot)
    print(json.dumps({key: current.get(key) for key in (
        "id", "status", "phase", "run_dir", "auto_ml_log_dir", "auto_ml_workspace_dir", "report_dir", "last_error",
    )}, ensure_ascii=False))
    resumed = args.output / "autorealize-resume.json"
    if resumed.exists():
        job = json.loads(resumed.read_text(encoding="utf-8"))
        state = request("http://127.0.0.1:18101", "/jobs/" + job["job_id"])
        print(json.dumps({key: state.get(key) for key in ("job_id", "status", "exit_code", "last_error")}, ensure_ascii=False))


def resume_realize(args):
    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    current = next(item for item in request(args.gateway, "/api/tasks") if item["id"] == task["id"])
    if current["status"] == "running":
        raise RuntimeError("Stop the existing validation task before resuming its cached AutoRealize stage.")
    job = request("http://127.0.0.1:18101", "/jobs/start", {
        "task_id": task["id"], "input_root": task["input_root"], "output_root": current["run_dir"],
        "run_name": "autorealize", "task_hint": task["config"]["auto_realize"]["task_hint"],
        "config_path": str(ROOT / "frontend" / "backend" / ".state" / (task["id"] + ".autorealize.config.yaml")),
        "python_executable": sys.executable, "working_dir": str(ROOT / "core" / "AutoRealize"),
        "env_overrides": {"DEEPSEEK_API_KEY": os.environ["AUTODECISION_TEST_API_KEY"]},
    })
    save(args.output / "autorealize-resume.json", job)
    print(json.dumps(job, ensure_ascii=False), flush=True)


def rebuild_handoff(args):
    """Recompile deterministic artifacts after a producer fix without rerunning paid cognition."""
    from types import SimpleNamespace

    sys.path.insert(0, str(ROOT / "core" / "AutoRealize"))
    from autorealize.config import AutoRealizeConfig
    from autorealize.models import DescriptionProtocolBundle, EvaluationContractReview, FileSummary, SampleSubmissionSpec
    from autorealize.modules.task_definition import TaskDefinitionModule
    from autorealize.modules.types import RuntimeServices
    from autorealize.prompts.manager import PromptManager
    from autorealize.report_writer import build_data_schema_contract
    from autorealize.trajectory import TrajectoryLogger

    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    current = next(item for item in request(args.gateway, "/api/tasks") if item["id"] == task["id"])
    stage = Path(current["run_dir"]) / "autorealize"
    report = stage / "realize_report"
    task_report = json.loads((report / "task_definition_report.json").read_text(encoding="utf-8"))
    original_evaluation_id = task_report["automl_context_pack"]["execution_contract"]["evaluation_id"]
    cognition = json.loads((report / "data_cognition_report.json").read_text(encoding="utf-8"))
    context = task_report["downstream_context"]
    files = [FileSummary.model_validate(item) for item in cognition["files"]]
    schema = build_data_schema_contract(files)
    spec = SampleSubmissionSpec.model_validate(context["sample_submission_spec"])
    spec.validation_rules = [rule for rule in spec.validation_rules if not rule.startswith("AutoRealize could not resolve source field alias ")]
    corrections = TaskDefinitionModule._correct_sample_spec_source_fields(spec, schema_contract=schema)
    context["sample_submission_spec"] = spec.model_dump()
    context["source_alias_guard"] = TaskDefinitionModule._collect_source_alias_guard(
        sample_spec=spec, schema_contract=schema, downstream_context=context,
    )
    for entry in context["source_alias_guard"]:
        if entry["alias"] in {"train.csv.weekday", "predict.csv.weekday"}:
            assert entry.get("exact_physical_column") == "weekday", entry
    assert not any(entry["alias"] in {"train", "predict", "csv"} for entry in context["source_alias_guard"])
    config = AutoRealizeConfig.from_file(report / "final_config.yaml")
    services = RuntimeServices(
        llm_client=SimpleNamespace(), prompt_mgr=PromptManager(config), registry=SimpleNamespace(),
        trajectory=TrajectoryLogger(report),
    )
    module = TaskDefinitionModule(config, services, stage, report)
    module._current_data_root = stage
    bundle = DescriptionProtocolBundle.model_validate(task_report["description_protocol_bundle"])
    evaluation = EvaluationContractReview.model_validate(task_report["evaluation_contract"])
    pack = module._write_automl_context_pack(
        protocol_bundle=bundle, file_summaries=files, downstream_context=context,
        evaluation_contract=evaluation, relations=cognition.get("relations", []),
    )
    main = task_report["main_task_protocol"]
    main["automl_context_pack"] = pack
    main["execution_contract"] = pack["execution_contract"]
    main["sample_submission_spec"] = spec.model_dump()
    main["sample_submission_status"].update({"validation_scope": "sample_schema_only", "final_prediction_validated": False})
    task_report["automl_context_pack"] = pack
    task_report["main_task_protocol"] = main
    task_report["downstream_context"] = context
    fix_report = {
        "scope": "deterministic_handoff_rebuild", "source": "saved authoritative task report and exact schema",
        "resolved_issue_ids": ["ACR-001", "ACR-002"],
        "residual_issue_ids": ["ACR-003"],
        "checks": ["Known filenames no longer become field aliases", "Qualified weekday references resolve to exact physical column", "Sample schema validation is explicitly separate from final prediction validation"],
        "source_field_corrections": corrections,
        "evaluation_id_unchanged": main["execution_contract"]["evaluation_id"] == original_evaluation_id,
        "note": "Original LLM audit remains available; no model performance or final prediction acceptance was fabricated.",
    }
    save(report / "main_task_protocol.json", main)
    save(report / "task_definition_report.json", task_report)
    submission = json.loads((report / "submission_report.json").read_text(encoding="utf-8"))
    submission.update({"validation_scope": "sample_schema_only", "final_prediction_validated": False})
    save(report / "submission_report.json", submission)
    save(report / "deterministic_handoff_repairs.json", fix_report)
    save(args.output / "handoff-rebuild.json", fix_report)
    print(json.dumps(fix_report, ensure_ascii=False), flush=True)


def verify_inference(args):
    """Called in a fresh Python process; fail immediately if generated inference fits a model."""
    import numpy as np
    import pandas as pd

    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    current = next(item for item in request(args.gateway, "/api/tasks") if item["id"] == task["id"])
    workspace = Path(current["auto_ml_workspace_dir"])
    exported = workspace / "best_solution"
    manifest = json.loads((exported / "solution_manifest.json").read_text(encoding="utf-8"))
    artifact = Path(manifest["artifact_path"])
    if not artifact.is_absolute():
        artifact = exported / artifact
    before = hashlib.sha256(artifact.read_bytes()).hexdigest()
    data = pd.read_csv(Path(task["input_root"]) / "predict.csv")
    spec = importlib.util.spec_from_file_location("validated_solution", exported / "solution.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module

    def block_training(frame, event, arg):
        if event == "call" and frame.f_code.co_name in {"fit", "fit_transform", "partial_fit", "train", "train_policy"}:
            raise AssertionError("Inference unexpectedly entered a training function: " + frame.f_code.co_name)

    sys.setprofile(block_training)
    try:
        spec.loader.exec_module(module)
        result = getattr(module, manifest["entrypoint"])(str(artifact), data.copy())
        repeated = getattr(module, manifest["entrypoint"])(str(artifact), data.copy())
    finally:
        sys.setprofile(None)
    values = result["sales"].to_numpy() if isinstance(result, pd.DataFrame) else np.asarray(result).reshape(-1)
    repeat_values = repeated["sales"].to_numpy() if isinstance(repeated, pd.DataFrame) else np.asarray(repeated).reshape(-1)
    for prediction in (result, repeated):
        if isinstance(prediction, pd.DataFrame) and "row_id" in prediction.columns:
            assert prediction["row_id"].tolist() == data["row_id"].tolist(), "Inference reordered row identities"
    assert len(values) == len(data), "Wrong prediction count"
    assert np.isfinite(values).all() and (values >= 0).all(), "Invalid prediction values"
    assert np.allclose(values, repeat_values, rtol=0, atol=1e-10), "Inference is not repeatable"
    after = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert before == after, "Inference modified the model artifact"
    output = pd.DataFrame({"row_id": data["row_id"], "sales": values}, columns=["row_id", "sales"])
    saved_submission = pd.read_csv(workspace / "best_submission" / "submission.csv")
    assert list(saved_submission.columns) == ["row_id", "sales"], "Wrong saved output schema"
    assert saved_submission["row_id"].tolist() == data["row_id"].tolist(), "Saved output row identities differ"
    assert np.allclose(values, saved_submission["sales"].to_numpy(), rtol=0, atol=1e-8), "Reloaded predictions differ from selected candidate output"
    output.to_csv(args.output / "reloaded-predictions.csv", index=False)
    result = {
        "passed": True, "fresh_process": True, "node_id": manifest["node_id"],
        "entrypoint": manifest["entrypoint"], "artifact": str(artifact),
        "artifact_sha256": before, "prediction_rows": len(output), "columns": list(output.columns),
        "checks": ["Fresh process imports exported solution", "No training function called", "Model artifact unchanged", "Repeated predictions identical", "Finite nonnegative predictions", "Exact row identity and output schema", "Reloaded predictions match selected candidate submission"],
        "evaluation_protocol": manifest.get("evaluation_protocol", {}),
    }
    save(args.output / "inference-verification.json", result)
    save(exported / "inference-verification.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def summarize(args):
    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    current = next(item for item in request(args.gateway, "/api/tasks") if item["id"] == task["id"])
    run_root = Path(current["run_dir"])
    stage_usage = []
    for path in sorted(run_root.rglob("llm_usage.jsonl")):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        provider = [row for row in records if row.get("source") == "provider"]
        stage_usage.append({
            "path": str(path.relative_to(run_root)), "provider_calls": len(provider),
            "local_cache_hits": sum(row.get("source") == "local_cache" for row in records),
            "models": sorted({str(row.get("model")) for row in provider}),
            "provider_tokens": sum(int(row.get("total_tokens") or 0) for row in provider),
        })
    report_root = Path(current["report_dir"]) if current.get("report_dir") else run_root / "report"
    trace_path = report_root / "report_trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.exists() else {}
    report_usage = trace.get("llm_usage", [])
    stage_usage.append({"path": str(trace_path), "provider_calls": len(report_usage),
                        "provider_tokens": sum(int(row.get("total_tokens") or 0) for row in report_usage),
                        "local_cache_hits": 0})
    smoke = json.loads((args.output / "provider-smoke.json").read_text(encoding="utf-8"))
    inference_path = args.output / "inference-verification.json"
    inference = json.loads(inference_path.read_text(encoding="utf-8")) if inference_path.exists() else {}
    training_path = args.output / "training-verification.json"
    training = json.loads(training_path.read_text(encoding="utf-8")) if training_path.exists() else {}
    adapter_path = args.output / "training-adapter-verification.json"
    adapter = json.loads(adapter_path.read_text(encoding="utf-8")) if adapter_path.exists() else {}
    replay_path = args.output / "replay-verification.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8")) if replay_path.exists() else {}
    metadata_path = Path(current["auto_ml_workspace_dir"]) / "working" / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    selected_node_id = str(inference.get("node_id") or "")
    metadata_matches_export = bool(selected_node_id and selected_node_id in str(metadata.get("artifact") or ""))
    journal = json.loads((Path(current["auto_ml_log_dir"]) / "journal.json").read_text(encoding="utf-8"))
    nodes = journal.get("nodes", [])
    accepted = [row for row in nodes if row.get("search_eligible") is True and row.get("is_buggy") is False]
    search_state_path = Path(current["auto_ml_log_dir"]) / "run_status.json"
    search_state = json.loads(search_state_path.read_text(encoding="utf-8")) if search_state_path.exists() else {}
    report_path = report_root / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    result = {
        "task_id": task["id"], "task_status": current["status"], "phase": current["phase"],
        "synthetic_data": True, "provider_smoke": smoke, "stage_usage": stage_usage,
        "pipeline_completed_provider_calls": sum(row["provider_calls"] for row in stage_usage),
        "pipeline_reported_provider_tokens": sum(row["provider_tokens"] for row in stage_usage),
        "provider_smoke_attempts": len(smoke),
        "local_cache_hits": sum(row["local_cache_hits"] for row in stage_usage),
        "accepted_mcts_candidates": len(accepted), "search_state": search_state,
        "accepted_fusion_candidates": sum(row.get("stage") == "fusion" for row in accepted),
        "selected_model_metadata_matches_export": metadata_matches_export,
        "actual_selected_model": metadata if metadata_matches_export else {},
        "inference": inference, "configured_training": training, "delivery_training_adapter": adapter,
        "replay": replay,
        "report_summary": report.get("summary", {}),
        "report_path": str(report_root / "report.md"),
        "limitations": [
            "Synthetic integration fixture; validation MAE is not an external business forecast.",
            "Accepted MCTS candidate and fusion counts reflect only persisted, eligible results; interrupted searches retain their original termination status.",
            "Internal model configurations are not independent MCTS nodes.",
            "Usage totals count completed provider records; canceled in-flight requests may not be recorded or billed consistently by the provider.",
        ],
    }
    save(args.output / "validation-summary.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def verify_training(args):
    """Verify retraining with the selected sidecar configuration explicitly supplied."""
    import joblib
    import numpy as np
    import pandas as pd

    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    current = next(item for item in request(args.gateway, "/api/tasks") if item["id"] == task["id"])
    workspace = Path(current["auto_ml_workspace_dir"])
    exported = workspace / "best_solution"
    manifest = json.loads((exported / "solution_manifest.json").read_text(encoding="utf-8"))
    original_artifact = Path(manifest["artifact_path"])
    if not original_artifact.is_absolute():
        original_artifact = exported / original_artifact
    original_hash = hashlib.sha256(original_artifact.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("validated_training_solution", exported / "solution.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    selected_config_path = workspace / "working" / "selected_config.json"
    selected_config = json.loads(selected_config_path.read_text(encoding="utf-8"))
    assert joblib.load(original_artifact)["config"] == selected_config, "Configuration does not belong to selected artifact"
    artifact_dir = args.output / "retrained-model-artifacts"
    artifact_dir.mkdir(exist_ok=False)
    shutil.copy2(selected_config_path, artifact_dir / "selected_config.json")
    shutil.copy2(selected_config_path, exported / "selected_config.json")
    training_data = pd.read_csv(Path(task["input_root"]) / "train.csv")
    prediction_data = pd.read_csv(Path(task["input_root"]) / "predict.csv")
    artifact = getattr(module, manifest["train_entrypoint"])(training_data, str(artifact_dir))
    assert joblib.load(artifact)["config"] == selected_config, "Retraining used a different configuration"
    predictions = np.asarray(getattr(module, manifest["entrypoint"])(artifact, prediction_data)).reshape(-1)
    selected_submission = pd.read_csv(workspace / "best_submission" / "submission.csv")
    assert len(predictions) == len(prediction_data), "Wrong prediction count"
    assert np.allclose(predictions, selected_submission["sales"].to_numpy(), rtol=0, atol=1e-8), "Retrained predictions differ from selected artifact"
    assert hashlib.sha256(original_artifact.read_bytes()).hexdigest() == original_hash, "Original artifact was modified"
    result = {
        "passed": True, "fresh_process": True, "node_id": manifest["node_id"],
        "requires_selected_config_copy": True, "unconfigured_training_verified": False,
        "selected_config": selected_config, "training_rows": len(training_data),
        "prediction_rows": len(prediction_data), "retrained_artifact": str(artifact),
        "checks": ["Sidecar configuration matches original selected artifact", "Explicit configuration copied before training", "Retrained artifact uses selected configuration", "Retrained predictions match selected submission", "Original artifact unchanged"],
        "limitation": "The generated train(data, artifact_dir) uses a different fallback configuration when selected_config.json is absent. Copy the delivered selected_config.json into every new artifact_dir before retraining; this test verifies that explicit setup only.",
    }
    save(args.output / "training-verification.json", result)
    save(exported / "training-verification.json", result)
    (exported / "TRAINING_CONFIGURATION.md").write_text(
        "# Reproducing the selected training configuration\n\n"
        "The delivered model and independently verified inference use Ridge with alpha=0.1, degree=1, seed=2025.\n\n"
        "Before calling train(data, artifact_dir), create artifact_dir and copy the accompanying "
        "selected_config.json into that directory. Pass the labelled train.csv as a pandas DataFrame. "
        "The function returns the saved model path for predict(model_path, data).\n\n"
        "This setup was tested in a fresh process with all 28 labelled fixture rows; the six predictions "
        "matched the original selected model. See training-verification.json.\n\n"
        "Limitation: calling train on an empty directory without that configuration silently uses "
        "the generated fallback alpha=10.0, degree=2. That path does not reproduce the selected model "
        "and is not covered by the passing configured-training result. The generated solution.py is preserved.\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


def verify_training_adapter(args):
    import numpy as np
    import pandas as pd

    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    current = next(item for item in request(args.gateway, "/api/tasks") if item["id"] == task["id"])
    workspace = Path(current["auto_ml_workspace_dir"])
    exported = workspace / "best_solution"
    manifest = json.loads((exported / "solution_manifest.json").read_text(encoding="utf-8"))
    original_solution_hash = hashlib.sha256((exported / "solution.py").read_bytes()).hexdigest()
    adapter = exported / "retrain.py"
    shutil.copy2(ROOT / "scripts" / "sales-validation-retrain.py", adapter)
    artifact_dir = args.output / "adapter-retrained-artifacts"
    if artifact_dir.exists():
        raise RuntimeError("Adapter verification already has an artifact directory; use a clean validation output.")
    output_csv = args.output / "adapter-retrained-predictions.csv"
    result = subprocess.run([
        sys.executable, str(adapter), "--train-data", str(Path(task["input_root"]) / "train.csv"),
        "--artifact-dir", str(artifact_dir), "--predict-data", str(Path(task["input_root"]) / "predict.csv"),
        "--output-csv", str(output_csv),
    ], capture_output=True, text=True, check=True, timeout=90)
    generated = pd.read_csv(output_csv)
    selected = pd.read_csv(workspace / "best_submission" / "submission.csv")
    assert list(generated.columns) == ["row_id", "sales"], "Wrong adapter output schema"
    assert generated["row_id"].tolist() == selected["row_id"].tolist(), "Adapter reordered row identity"
    assert np.allclose(generated["sales"].to_numpy(), selected["sales"].to_numpy(), rtol=0, atol=1e-8), "Adapter did not reproduce selected predictions"
    assert hashlib.sha256((exported / "solution.py").read_bytes()).hexdigest() == original_solution_hash, "Adapter modified original solution"
    provenance = {
        "kind": "derived_delivery_training_adapter", "node_id": manifest["node_id"],
        "training_entrypoint": "retrain.train", "inference_entrypoint": "retrain.predict",
        "adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
        "original_solution_sha256": original_solution_hash,
        "selected_config_sha256": hashlib.sha256((exported / "selected_config.json").read_bytes()).hexdigest(),
        "source_template": "scripts/sales-validation-retrain.py",
        "original_solution_modified": False, "historical_score_modified": False,
        "behavior": "Provide the delivered selected_config.json in every new artifact_dir, then delegate to the original generated train and predict functions. Reject a conflicting existing configuration.",
    }
    verification = {"passed": True, "fresh_process": True, "new_artifact_directory": True,
                    "prediction_rows": len(generated), "matches_selected_predictions": True,
                    "cli_result": json.loads(result.stdout.strip()), "provenance": provenance}
    save(exported / "delivery_adapter.json", provenance)
    save(exported / "training-adapter-verification.json", verification)
    save(args.output / "training-adapter-verification.json", verification)
    with (exported / "TRAINING_CONFIGURATION.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n## Automatic delivery adapter\n\n"
            "Use retrain.train(data, artifact_dir) for retraining with automatic selected configuration setup, "
            "or run python retrain.py --train-data PATH_TO_TRAIN_CSV --artifact-dir NEW_ARTIFACT_DIR "
            "--predict-data PATH_TO_PREDICT_CSV --output-csv OUTPUT_CSV.\n\n"
            "This derived delivery adapter preserves solution.py and delegates its training and inference "
            "functions after supplying selected_config.json. It rejects a conflicting existing configuration. "
            "A fresh-process CLI run into a new directory reproduced the six original predictions. "
            "See delivery_adapter.json for source hashes and training-adapter-verification.json for checks.\n"
        )
    print(json.dumps(verification, ensure_ascii=False), flush=True)


def verify_replay(args):
    task = json.loads((args.output / "task.json").read_text(encoding="utf-8"))
    base = f"/api/tasks/{task['id']}/replay"
    replay = request(args.gateway, base)
    events = replay["events"]
    head = request(args.gateway, base + "/snapshot?sequence=0")
    tail = request(args.gateway, base + f"/snapshot?sequence={len(events)}")
    assert not head["auto_ml"]["nodes"] and not head["auto_ml"]["pending_nodes"], "Future nodes leaked into replay start"
    assert not head["auto_ml"].get("best_solution_code"), "Future code leaked into replay start"
    assert not head["auto_report"].get("report_markdown"), "Future report leaked into replay start"
    report_event = next(row for row in events if row.get("payload", {}).get("snapshot", {}).get("auto_report", {}).get("report_markdown"))
    before_report = request(args.gateway, base + f"/snapshot?sequence={report_event['sequence'] - 1}")
    assert not before_report["auto_report"].get("report_markdown"), "Report leaked before its recorded event"
    scored_event = next(row for row in events if isinstance(row.get("payload", {}).get("node", {}).get("metric"), (int, float)))
    before_score = request(args.gateway, base + f"/snapshot?sequence={scored_event['sequence'] - 1}")
    node_id = scored_event["payload"]["node"]["id"]
    previous = [row for key in ("nodes", "pending_nodes") for row in before_score["auto_ml"][key] if row["id"] == node_id]
    assert not previous or previous[0].get("metric") is None, "Future metric leaked before scored node event"
    assert tail["task"].get("status") == "completed", "Replay lost completed task state"
    assert tail["auto_report"].get("report_markdown"), "Replay lost final report"
    assert tail["auto_ml"].get("best_node_id") == node_id, "Replay lost selected node"
    result = {"passed": True, "task_id": task["id"], "events": len(events), "fidelity": replay["fidelity"],
              "first_score_sequence": scored_event["sequence"], "report_sequence": report_event["sequence"],
              "checks": ["Empty replay start contains no future nodes, code, or report", "Score hidden until scored node event", "Report hidden until recorded report event", "Final selected node and completed report restored"]}
    save(args.output / "replay-verification.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["submit", "status", "resume-realize", "rebuild-handoff", "verify-inference", "verify-training", "verify-training-adapter", "verify-replay", "summarize"])
    parser.add_argument("--gateway", default="http://127.0.0.1:18080")
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / "live-validation-20260906")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        {"submit": submit, "status": status, "resume-realize": resume_realize,
         "rebuild-handoff": rebuild_handoff, "verify-inference": verify_inference,
         "verify-training": verify_training, "verify-training-adapter": verify_training_adapter,
         "verify-replay": verify_replay, "summarize": summarize}[args.action](args)
    except Exception as exc:
        secret = os.environ.get("AUTODECISION_TEST_API_KEY", "")
        message = str(exc).replace(secret, "[REDACTED]") if secret else str(exc)
        print(json.dumps({"error": message[:1500]}, ensure_ascii=False), flush=True)
        raise SystemExit(1)
