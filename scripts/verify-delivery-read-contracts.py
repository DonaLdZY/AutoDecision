"""Verify generated sheet readers against actual delivery workbooks, without an LLM."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

os.environ.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.models import FileSummary, DescriptionProtocolBundle
from autorealize.report_writer import build_data_access_protocol, build_automl_context_pack


def verify_profile_readers(files, input_root):
    import pandas as pd
    checks = []
    for fs in files:
        for sheet in fs.source_metadata.get("excel_sheet_profiles", []):
            kwargs = {"sheet_name": sheet["sheet_name"], "header": 0, "skiprows": 0}
            if Path(fs.path).suffix.lower() == ".xlsx":
                kwargs["engine"] = "openpyxl"
            frame = pd.read_excel(input_root / fs.path, **kwargs)
            if [str(value) for value in frame.columns] != sheet.get("columns", []):
                raise RuntimeError(f"Actual original profile reader does not reproduce source columns: {fs.path}::{sheet['sheet_name']}")
            contract = {"schema_version": "autorealize.excel_read_contract.v1", "pandas_kwargs": kwargs,
                        "columns_exact": list(sheet.get("columns", [])), "read_parameters_verified": True,
                        "verification_scope": "actual_source_read_reproduces_preserved_profile_columns"}
            sheet["profiled_read_contract"] = contract
            checks.append({"table_id": f"{fs.path}::{sheet['sheet_name']}", "actual_shape": list(frame.shape),
                           "previous_layout": sheet.get("layout_kind"), "previous_header": sheet.get("detected_header_row"),
                           "verified_reader": contract})
            sheet["layout_kind"] = "standard_table"
            sheet["detected_header_row"] = 0
            sheet["reading_risks"] = [
                risk for risk in (sheet.get("reading_risks") or [])
                if not any(term in str(risk).lower() for term in ("header", "表头"))
            ]
            sheet["reading_risks"].append(
                "Actual header=0 source read reproduced all preserved columns; this verified reader supersedes earlier heuristic layout suggestions.")
            sheet["recommended_read"] = f"pd.read_excel(path, sheet_name={sheet['sheet_name']!r}, header=0)"
    return checks


def main():
    import pandas as pd
    spec = importlib.util.spec_from_file_location("delivery_reader_stages", ROOT / "scripts/industrial-stage-control.py")
    stages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stages)
    task = stages.current_task("delivery")
    cognition = stages.read_json(Path(task["run_dir"]) / "autorealize/realize_report/data_cognition_report.json")
    files = [FileSummary.model_validate(row) for row in cognition["files"]]
    input_root = Path(next(row for row in stages.read_json(stages.batch.OUT / "manifest.json")["tasks"]
                           if row["slug"] == "delivery")["payload"]["input_root"])
    actual_profiles = verify_profile_readers(files, input_root)
    cards = [{"table_id": f"{fs.path}::{sheet['sheet_name']}", "source_file": fs.path,
              "sheet_name": sheet["sheet_name"]} for fs in files
             for sheet in fs.source_metadata.get("excel_sheet_profiles", [])]
    pack = build_automl_context_pack(DescriptionProtocolBundle(data_access=build_data_access_protocol(files)),
                                   files, compiled_context={"table_cards": cards})
    checks = []
    for row in pack.data_access:
        contract = row.get("read_contract", {})
        assert contract, row["table_id"]
        frame = pd.read_excel(input_root / row["path"], **contract["pandas_kwargs"])
        if contract["column_access"] == "integer_position":
            assert list(frame.columns) == list(range(frame.shape[1]))
            assert not row.get("columns")
        else:
            assert [str(value) for value in frame.columns] == contract["columns_exact"], row["table_id"]
        checks.append({"table_id": row["table_id"], "shape": list(frame.shape),
                       "kwargs": contract["pandas_kwargs"], "column_access": contract["column_access"]})
    dest = stages.batch.OUT / "optimization-validation" / f"delivery-readers-{time.time_ns()}"
    result = {"passed": True, "readers_checked": len(checks), "checks": checks, "profile_checks": actual_profiles,
              "scope": "Actual source sheet reads and column verification. No date imputation, modeling, or operational benefit claim."}
    stages.batch.save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "passed": True, "readers_checked": len(checks)}))


if __name__ == "__main__":
    main()
