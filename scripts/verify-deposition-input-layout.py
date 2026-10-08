"""Exercise the unchanged first candidate's data loader against a verified input layout."""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout-result", required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("layout_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    record = stages.read_json(args.layout_result)
    if record.get("passed") is not True or record["slug"] != "deposition":
        raise RuntimeError("Expected a verified deposition layout")
    task = stages.current_task("deposition")
    journal = stages.read_json(Path(task["auto_ml_log_dir"]) / "journal.json")
    node = next(node for node in journal["nodes"] if node["id"] == "5b6ef1f8953946e1a55afd0224741365")
    code = node["code"]
    ast.parse(code)
    namespace = {"__name__": "deposition_layout_probe", "__file__": str(args.layout_result.parent / "original_candidate.py")}
    exec(compile(code, namespace["__file__"], "exec"), namespace)
    result = {"node_id": node["id"], "code_unchanged": True, "model_training_performed": False,
              "final_evaluation_performed": False, "input_layout": str(args.layout_result)}
    try:
        frame, mappings, audit, exclusions, facts = namespace["build_dataset"](Path(record["candidate"]))
        result.update(passed=True, rows=len(frame), mapping_rows=len(mappings), audit_rows=len(audit),
                      exclusion_rows=len(exclusions), facts=facts,
                      split_counts=frame["split"].value_counts().to_dict())
    except Exception as exc:
        result.update(passed=False, error_type=type(exc).__name__, error=str(exc))
    stages.batch.save(args.layout_result.parent / "original-loader-review.json", result)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
