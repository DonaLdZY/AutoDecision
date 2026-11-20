from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import app
import algorithm_library


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, value) -> Path:
    return _write(path, json.dumps(value, ensure_ascii=False))


def _autorealize(tmp_path: Path, *, target: str = "是否故障", metric: str = "Average Precision", direction: str = "maximize") -> Path:
    root = tmp_path / "autorealize"
    _write(root / "train.csv", f"记录编号,主轴扭矩_kgfm,{target}\n1,1.0,0\n2,2.0,1\n3,3.0,0\n4,4.0,1\n")
    _write(root / "predict.csv", "记录编号,主轴扭矩_kgfm\n5,5.0\n6,6.0\n")
    _write(root / "sample_submission.csv", "记录编号,故障概率\n5,0\n6,0\n")
    _write(root / "description.md", "预测故障\n")
    _write_json(root / "realize_report" / "problem_paradigm_report.json", {"problem_structure": "prediction"})
    _write_json(
        root / "realize_report" / "evaluation_contract_report.json",
        {"final": {"primary_metric": metric, "metric_direction": direction}},
    )
    return root


def _task(tmp_path: Path, *, run_name: str = "run", mode: str = "auto", steps: int = 50, **config):
    config_payload = app.AutoMLConfigPayload(
        reuse_package_mode=mode,
        steps=steps,
        **config,
    )
    run_dir = tmp_path / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        id="task-1",
        task_name="spindle-failure-anon",
        run_dir=str(run_dir),
        report_dir=str(run_dir / "report"),
        auto_ml_log_dir=str(run_dir / "automl" / "logs" / "run"),
        auto_ml_workspace_dir=str(run_dir / "automl" / "workspaces" / "run"),
        config=SimpleNamespace(auto_ml=config_payload, auto_realize=SimpleNamespace()),
    )


def _card(tmp_path: Path, signature, *, package_id: str = "pkg-1", development=80.0, baseline=40.0, solution: str = "def train(data, artifact_dir):\n    return {}\n"):
    package = tmp_path / "library" / package_id
    _write(package / "solution" / "solution.py", solution)
    _write_json(
        package / "solution" / "solution_manifest.json",
        {
            "node_id": "node-1",
            "kind": "prediction",
            "entrypoint": "predict",
            "artifact_path": "model_artifacts/working/artifact/model_test.joblib",
        },
    )
    _write_json(
        package / algorithm_library.CARD_FILENAME,
        {
            "package_id": package_id,
            "signature": signature,
            "scores": {"development": development, "single_metric": baseline},
            "solution": {"node_number": 14, "journal_node": {"id": "node-1", "method_family": "tree_boosting"}},
            "source": {"task_id": "source-task"},
        },
    )
    return algorithm_library.load_cards()[0]


def test_distillation_uses_reselected_solution_and_rejects_prior_knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr(algorithm_library, "LIBRARY_ROOT", tmp_path / "library")
    task = _task(tmp_path)
    workspace = Path(task.auto_ml_workspace_dir)
    _write(workspace / "top_solution" / "top4" / "solution.py", "TOP4\n")
    _write_json(workspace / "top_solution" / "top4" / "solution_manifest.json", {"node_id": "node-14"})
    _write_json(
        Path(task.auto_ml_log_dir) / "journal.json",
        {"nodes": [{"id": "node-14", "stage": "draft", "method_family": "tree_boosting"}, {"id": "bad", "stage": "draft", "is_buggy": True, "method_family": "linear"}]},
    )
    _write_json(
        Path(task.report_dir) / "producer_facts.json",
        {
            "算法竞争": {
                "胜出编号": 14,
                "胜出方法": "梯度提升树",
                "候选": [{"编号": 14, "借用已知规则": False}, {"编号": 22, "借用已知规则": True}],
                "系统选中方案的自报验证成绩": 85.1,
                "系统选中方案的验收集成绩": 89.8,
                "改选说明": {"系统原选方案编号": 22, "改用方案编号": 14},
            },
            "先验知识检查": {"检查的方案数": 29, "引用了已知名称或阈值的方案数": 6, "明细": {"#22": ["known"]}},
            "预警效果": {"单一指标说明": {"指标": "主轴扭矩", "验收集平均精度": 47.2}},
            "交付物": {"交付目录": "top_solution/top4", "复用核对": {"输出条数": 2000}},
            "发现": {"最终方案自己构造的组合指标（摘自代码）": [{"新指标名": "x"}]},
        },
    )
    result = algorithm_library.distill_task_package(task, version="test")
    assert result["status"] == "created"
    card = json.loads((Path(result["card"])).read_text(encoding="utf-8"))
    assert card["solution"]["node_number"] == 14
    assert (Path(result["card"]).parent / "solution" / "solution.py").read_text(encoding="utf-8") == "TOP4\n"
    assert card["experience"]["failed_families"][0]["method_family"] == "linear"

    # A solution that borrowed known rules must never enter the library.
    facts = json.loads((Path(task.report_dir) / "producer_facts.json").read_text(encoding="utf-8"))
    facts["算法竞争"]["改选说明"] = {"改用方案编号": 22}
    _write_json(Path(task.report_dir) / "producer_facts.json", facts)
    assert algorithm_library.distill_task_package(task)["status"] == "skipped"


def test_reuse_decision_covers_direct_hot_and_normal_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(algorithm_library, "LIBRARY_ROOT", tmp_path / "library")
    autorealize = _autorealize(tmp_path)
    signature = algorithm_library.task_signature(autorealize)
    _card(tmp_path, signature)

    direct = algorithm_library.decide_reuse(_task(tmp_path, run_name="direct"), autorealize)
    assert direct["action"] == "direct_reuse"
    assert direct["score"] >= 0.85

    hot = algorithm_library.decide_reuse(_task(tmp_path, run_name="hot", mode="hot_start_only"), autorealize)
    assert hot["action"] == "hot_start"
    assert hot["hot_start"]["steps"] == 15
    assert Path(hot["hot_start"]["task_json_path"]).is_file()

    other = _autorealize(tmp_path / "other", target="销量", metric="MAE", direction="minimize")
    normal = algorithm_library.decide_reuse(_task(tmp_path, run_name="normal"), other)
    assert normal["action"] == "normal"
    assert "不一致" in normal["reason"] or "缺少输入字段" in normal["reason"]


def test_direct_reuse_downgrades_to_hot_start_when_tolerance_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(algorithm_library, "LIBRARY_ROOT", tmp_path / "library")
    autorealize = _autorealize(tmp_path)
    signature = algorithm_library.task_signature(autorealize)
    _card(tmp_path, signature, development=95.0)
    task = _task(tmp_path, run_name="downgrade")
    task.config.auto_ml.reuse_score_tolerance = 0

    monkeypatch.setattr(
        algorithm_library,
        "run_direct_reuse",
        lambda *args, **kwargs: {"ok": False, "reason": "复用后开发集分数 90 低于记录成绩 95 的容忍范围"},
    )
    action = app._apply_package_reuse(task, autorealize, Path(task.auto_ml_log_dir), Path(task.auto_ml_workspace_dir))
    assert action == "hot"
    decision = json.loads((Path(task.run_dir) / "reuse_decision.json").read_text(encoding="utf-8"))
    assert decision["action"] == "hot_start"
    assert decision["direct_reuse_error"]
    assert decision["hot_start"]["steps"] == 15


def test_direct_reuse_retrains_and_writes_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(algorithm_library, "LIBRARY_ROOT", tmp_path / "library")
    autorealize = _autorealize(tmp_path)
    signature = algorithm_library.task_signature(autorealize)
    solution = (
        "from pathlib import Path\n"
        "import numpy as np\n"
        "def train(data, artifact_dir):\n"
        "    (Path(artifact_dir) / 'model.joblib').write_text('ok', encoding='utf-8')\n"
        "    return {'dev_ap': 90.0}\n"
        "def predict(model_path, data):\n"
        "    return np.full(len(data['predict']), 0.5)\n"
    )
    card = _card(tmp_path, signature, development=80.0, solution=solution)
    workspace = tmp_path / "workspace"
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    result = algorithm_library.run_direct_reuse(card, SimpleNamespace(id="task"), autorealize, workspace, log_dir, 0.0)
    assert result["ok"], result["reason"]
    assert (workspace / "best_solution" / "submission.csv").is_file()
    assert (log_dir / "journal.json").is_file()
    assert (workspace / "best_solution" / "model_artifacts" / "working" / "artifact" / "model_test.joblib").is_file()

    # Same package, recorded score above the fresh dev score, zero tolerance -> reject.
    monkeypatch.setitem(card["scores"], "development", 95.0)
    second = algorithm_library.run_direct_reuse(card, SimpleNamespace(id="task"), autorealize, tmp_path / "workspace2", log_dir, 0.0)
    assert not second["ok"]
    assert "容忍" in second["reason"]
