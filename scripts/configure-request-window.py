"""Set the active text model request limits without exposing credentials."""
import json
from pathlib import Path

import yaml


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / "runs/industrial-examples-20260907/settings.yaml"
    settings = yaml.safe_load(path.read_text(encoding="utf-8"))
    roles = settings["llm"]["roleModels"]
    active = {roles[role] for role in ("autoRealize", "autoMlCode", "autoMlFeedback")}
    changed = []
    for model in settings["llm"]["modelLibrary"]:
        if model["id"] in active:
            model["maxTokens"] = model["contextWindowTokens"] = 272 * 1024
            changed.append({"model": model["model"], "context_window": model["contextWindowTokens"],
                            "output_ceiling": model["maxTokens"]})
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(path)
    print(json.dumps(changed, ensure_ascii=False))


if __name__ == "__main__":
    main()
