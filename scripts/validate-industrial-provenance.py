"""Re-extract actual chemical document evidence with production cognition and memory stages."""
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "runs/industrial-examples-20260907"
sys.path.insert(0, str(ROOT / "core/AutoRealize"))
from autorealize.cognition import _summarize_document_full_text
from autorealize.config import AutoRealizeConfig
from autorealize.llm.client import LLMClient
from autorealize.models import FileSummary
from autorealize.modules.data_cognition import DataCognitionModule
from autorealize.modules.types import RuntimeServices
from autorealize.pipeline import _extract_constraint_memory
from autorealize.prompts.manager import PromptManager
from autorealize.trajectory import TrajectoryLogger


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    dest = BATCH / "optimization-validation" / ("chemical-provenance-" + str(time.time_ns()))
    dest.mkdir(parents=True)
    logging.basicConfig(filename=dest / "validation.log", level=logging.INFO, encoding="utf-8")
    task = read(BATCH / "batch-state.json")["tasks"]["chemical"]
    source = Path(task["run_dir"]) / "autorealize"
    data_root = source / "data"
    old = read(source / "realize_report/data_cognition_report.json")
    save(dest / "old-cognition.json", old)
    cfg = AutoRealizeConfig.from_file(source / "realize_report/final_config.yaml")
    settings = yaml.safe_load((BATCH / "settings.yaml").read_text(encoding="utf-8-sig"))
    model = next(item for item in settings["llm"]["modelLibrary"] if item["id"] == settings["llm"]["roleModels"]["autoRealize"])
    assert model["model"] == "gpt-5.6-luna" and model["reasoningEffort"] == "xhigh" and model["apiKey"]
    cfg.llm.api_key, cfg.llm.base_url, cfg.llm.model_name = model["apiKey"], model["baseUrl"], model["model"]
    cfg.llm.reasoning_effort = "xhigh"
    cfg.llm.max_tokens = cfg.llm.minimum_output_tokens = cfg.llm.structured_max_tokens = 32768
    client = LLMClient(cfg, dest)
    prompt = PromptManager(cfg)
    module = DataCognitionModule(cfg, RuntimeServices(client, prompt, None, TrajectoryLogger(dest)), dest)
    result = {"passed": False, "started_at": time.time(), "source": str(source),
              "comparison": "Saved real old provider outputs versus fresh production outputs on the same original source documents"}
    save(dest / "result.json", result)
    print(str(dest), flush=True)
    try:
        files = [FileSummary.model_validate(item) for item in old["files"]]
        for file in files:
            if file.path.endswith(".docx"):
                text = module._read_authoritative_text(data_root / file.path)
                save(dest / "original-document.json", {"file": file.path, "text": text})
                output, trace = _summarize_document_full_text(
                    cfg=cfg, llm=client, prompt_mgr=prompt,
                    base_context={"file": file.path, "kind": "document", "task": old["task_hint"]},
                    full_text=text, relative_path=file.path,
                )
                file.summary, file.detailed_report = output.concise_summary, output.detailed_report
                file.extracted_knowledge, file.warnings = output.key_facts, output.risks
                file.related_files, file.key_entities, file.columns = output.related_hints, output.key_columns, output.key_columns
                file.source_metadata["document_cognition"] = trace
                save(dest / "new-document-cognition.json", file.model_dump())
        authority = module._extract_authoritative_memory(data_root=data_root, task_hint=old["task_hint"], file_summaries=files)
        save(dest / "new-authority.json", authority)
        constraints = _extract_constraint_memory(llm_client=client, prompt_mgr=prompt, file_summaries=files,
                                                task_hint=old["task_hint"], authoritative_memory=authority)
        save(dest / "new-constraints.json", constraints)
        revised = deepcopy(old)
        revised.update(files=[file.model_dump() for file in files], authoritative_memory=authority, constraint_memory=constraints)
        save(dest / "refreshed-cognition.json", revised)
        result.update(completed=True, checks={
            "physical_tables_unchanged": [row for row in revised["files"] if not row["path"].endswith(".docx")] ==
                                         [row for row in old["files"] if not row["path"].endswith(".docx")],
            "qdi_evidence_unchanged": revised["question_investigation"] == old["question_investigation"],
            "human_source_review_pending": True,
        })
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc).replace(model["apiKey"], "[REDACTED]"))
    finally:
        client.client.close()
    result["finished_at"] = time.time()
    save(dest / "result.json", result)
    print(json.dumps({"result": str(dest / "result.json"), "completed": result.get("completed", False)}), flush=True)


if __name__ == "__main__":
    main()
