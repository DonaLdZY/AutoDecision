from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_OUTPUTS = (
    "output_items.csv",
    "output_stacks.csv",
    "output_trucks.csv",
)


def parse_official_report(path: Path) -> dict:
    if not path.exists():
        return {
            "feasible": False,
            "official_checker_anomalies": ["official checker did not create report.csv"],
        }
    text = path.read_text(encoding="iso-8859-1", errors="replace")
    rows = list(csv.reader(text.splitlines(), delimiter=";"))
    rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if len(rows) >= 2 and rows[0][:3] == [
        "transportation cost",
        "inventory cost",
        "objective function",
    ]:
        try:
            transportation = float(rows[1][0].replace(",", "."))
            inventory = float(rows[1][1].replace(",", "."))
            objective = float(rows[1][2].replace(",", "."))
        except (IndexError, ValueError) as exc:
            return {
                "feasible": False,
                "official_checker_anomalies": [f"cannot parse official objective row: {exc}"],
                "official_report_text": text,
            }
        return {
            "feasible": True,
            "transportation_cost": transportation,
            "inventory_cost": inventory,
            "objective": objective,
            "official_checker_anomalies": [],
            "official_report_text": text,
        }

    anomalies = []
    for row in rows:
        if row and row[0].lower() == "scope":
            continue
        anomalies.append("; ".join(cell for cell in row if cell))
    return {
        "feasible": False,
        "objective": None,
        "official_checker_anomalies": anomalies or ["official report has an unknown format"],
        "official_report_text": text,
    }


def locate_checker(task_dir: Path) -> Path:
    candidate = task_dir.parent / "tools" / "checker" / "CheckerChallenge-1.11.4.jar"
    if not candidate.exists():
        candidate = (
            task_dir.parent.parent
            / "tools"
            / "checker"
            / "CheckerChallenge-1.11.4.jar"
        )
    if not candidate.exists():
        raise FileNotFoundError(f"official checker JAR not found: {candidate}")
    return candidate


def evaluate(task_dir: Path, submission_dir: Path, benchmark: dict) -> dict:
    missing = [name for name in REQUIRED_OUTPUTS if not (submission_dir / name).is_file()]
    if missing:
        return {
            "feasible": False,
            "objective": None,
            "violations": [f"missing required submission files: {missing}"],
        }
    if shutil.which("java") is None:
        return {
            "feasible": False,
            "objective": None,
            "violations": ["Java runtime is required for the official ROADEF checker"],
        }

    jar = locate_checker(task_dir)
    logback = jar.parent / "logback.xml"
    with tempfile.TemporaryDirectory(prefix="roadef-evaluation-") as temp_name:
        temp = Path(temp_name)
        data = temp / "data"
        logs = temp / "logs"
        data.mkdir()
        logs.mkdir()
        for name in ("input_items.csv", "input_trucks.csv", "input_parameters.csv"):
            shutil.copy2(task_dir / "input" / name, data / name)
        for name in REQUIRED_OUTPUTS:
            shutil.copy2(submission_dir / name, data / name)
        report_path = data / "report.csv"
        instances_path = temp / "instances.csv"
        instances_path.write_text(
            "input items pathFilename;input trucks pathFilename;input parameters pathFilename;"
            "output items pathFilename;output stacks pathFilename;output trucks pathFilename;"
            "report pathFilename\n"
            "data/input_items.csv;data/input_trucks.csv;data/input_parameters.csv;"
            "data/output_items.csv;data/output_stacks.csv;data/output_trucks.csv;data/report.csv\n",
            encoding="utf-8",
        )
        command = [
            "java",
            "-Xmx4g",
            "-DLOG_FILENAME=logs/logchecker",
            f"-Dlogback.configurationFile={logback}",
            "-jar",
            str(jar),
            str(instances_path),
        ]
        process = subprocess.run(
            command,
            cwd=temp,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        official = parse_official_report(report_path)
        report_copy = task_dir / "private_evaluation" / "official_checker_report.csv"
        if report_path.exists():
            shutil.copy2(report_path, report_copy)

    best_known = float(benchmark["best_known_objective"])
    objective = official.get("objective")
    gap = float(objective) - best_known if official.get("feasible") else None
    gap_percent = 100.0 * gap / best_known if gap is not None and best_known else None
    violations = list(official.get("official_checker_anomalies") or [])
    if process.returncode != 0:
        violations.append(f"official checker process exited with code {process.returncode}")
    if not official.get("feasible") and not violations:
        violations.append("official checker rejected the solution")
    return {
        "instance": benchmark["instance"],
        "feasible": bool(official.get("feasible")) and process.returncode == 0,
        "objective_name": "official_transportation_plus_inventory_cost",
        "objective": objective if official.get("feasible") else None,
        "transportation_cost": official.get("transportation_cost"),
        "inventory_cost": official.get("inventory_cost"),
        "best_known_objective": best_known,
        "absolute_gap": gap,
        "gap_percent": gap_percent,
        "reference_status": benchmark.get("reference_status"),
        "violations": violations,
        "official_checker_exit_code": process.returncode,
        "official_checker_stdout_tail": process.stdout[-8000:],
        "official_checker_stderr_tail": process.stderr[-8000:],
        "official_report_text": official.get("official_report_text", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-dir", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    private_dir = Path(__file__).resolve().parent
    task_dir = private_dir.parent
    benchmark = json.loads(
        (private_dir / "benchmark.json").read_text(encoding="utf-8-sig")
    )
    try:
        report = evaluate(task_dir, args.submission_dir.resolve(), benchmark)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        report = {"feasible": False, "objective": None, "violations": [str(exc)]}

    report_path = args.report or private_dir / "evaluation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("feasible") else 2


if __name__ == "__main__":
    raise SystemExit(main())
