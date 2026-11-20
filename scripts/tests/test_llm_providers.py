import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "test-llm-providers.py"
SPEC = importlib.util.spec_from_file_location("test_llm_providers", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_preferred_mode_stops_after_deepseek_is_available():
    calls = []

    def fake_probe(model, *_args):
        calls.append(model)
        return {"model": model, "available": model == "deepseek-v4.1-flash"}

    providers = [(name, "key", "base") for name in ("deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6-luna")]
    results = module.run_probes(providers, 10, "process", probe_fn=fake_probe)

    assert calls == ["deepseek-v4.1-flash"]
    assert [item.get("status") for item in results] == [None, "skipped_after_success", "skipped_after_success"]


def test_preferred_mode_falls_back_in_order_until_first_available():
    calls = []

    def fake_probe(model, *_args):
        calls.append(model)
        return {"model": model, "available": model == "glm-5.3-flash"}

    providers = [(name, "key", "base") for name in ("deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6-luna")]
    results = module.run_probes(providers, 10, "process", probe_fn=fake_probe)

    assert calls == ["deepseek-v4.1-flash", "glm-5.3-flash"]
    assert results[-1]["status"] == "skipped_after_success"


def test_all_mode_probes_every_provider():
    calls = []

    def fake_probe(model, *_args):
        calls.append(model)
        return {"model": model, "available": True}

    providers = [(name, "key", "base") for name in ("deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6-luna")]
    module.run_probes(providers, 10, "process", mode="all", probe_fn=fake_probe)

    assert calls == ["deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6-luna"]
