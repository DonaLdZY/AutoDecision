"""Separate-process entrypoint for explicit local solution trials (never train)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import site
import sys


def serializable(value):
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict(orient="records")
        except TypeError:
            return value.to_dict()
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Unsupported result type: {type(value).__name__}")


def materialize_frames(data, specifications):
    """Explicit JSON-to-DataFrame conversion, including nested history contracts.

    No code expressions, file reads, missing-column insertion or implicit column dropping.
    """
    if not specifications:
        return data
    import pandas as pd
    for spec in specifications:
        pointer, columns = spec['pointer'], spec['columns']
        if not columns or len(columns) != len(set(columns)):
            raise ValueError('DataFrame columns must be nonempty and unique')
        path = [p.replace('~1', '/').replace('~0', '~') for p in pointer[1:].split('/')] if pointer else []
        parent = None
        current = data
        key = None
        for part in path:
            parent = current
            key = int(part) if isinstance(current, list) else part
            current = current[key]
        if not isinstance(current, list):
            raise ValueError('DataFrame source must be a JSON array')
        for row in current:
            if isinstance(row, dict):
                if set(row) != set(columns):
                    raise ValueError('DataFrame record fields do not match explicit columns')
            elif not isinstance(row, list) or len(row) != len(columns):
                raise ValueError('DataFrame row does not match explicit columns')
        frame = pd.DataFrame(current, columns=columns)
        if parent is None:
            data = frame
        else:
            parent[key] = frame
    return data


def main():
    # Keep Python isolated from the working directory, PYTHONPATH and user startup
    # customization, while allowing dependencies intentionally installed for the
    # configured interpreter's user account (e.g. pandas on a local workstation).
    user_site = site.getusersitepackages()
    if isinstance(user_site, str) and Path(user_site).is_dir():
        site.addsitedir(user_site)
    root = Path(sys.argv[1]).resolve()
    request = json.loads((root / "trial_request.json").read_text(encoding="utf-8"))
    entrypoint = request["entrypoint"]
    if entrypoint not in {"predict", "solve", "rollout"}:
        raise ValueError("Only inference entrypoints are allowed")
    package = root / "solution"
    sys.path.insert(0, str(package))
    spec = importlib.util.spec_from_file_location("autodecision_trial_solution", package / "solution.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if request["input_mode"] == "csv":
        import pandas as pd
        data = pd.read_csv(root / "trial_input.csv")
    else:
        data = json.loads((root / "trial_input.json").read_text(encoding="utf-8"))
        data = materialize_frames(data, request.get('dataframes', []))
    model_path = str(package / request["model_path"]) if request.get("model_path") else None
    decision_code = request.get("decision_code")
    if decision_code:
        # -I excludes this script directory; add only our trusted host module.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from decision_program import run_program

        def run_model(value):
            result = getattr(module, entrypoint)(model_path, value)
            # Programs see plain JSON values, never model/DataFrame objects.
            return json.loads(json.dumps(result, ensure_ascii=False, default=serializable, allow_nan=False))

        result, decision = run_program(decision_code, data, run_model)
        (root / "trial_decision.json").write_text(
            json.dumps(decision, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    else:
        result = getattr(module, entrypoint)(model_path, data)
    encoded = json.dumps(result, ensure_ascii=False, default=serializable, allow_nan=False)
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Result exceeds the 1 MiB trial preview limit")
    (root / "trial_result.json").write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
