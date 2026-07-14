from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_quickstart_example_has_separate_target_and_submission_contract() -> None:
    root = ROOT / "examples" / "quickstart" / "input"
    train = _rows(root / "train.csv")
    predict = _rows(root / "predict.csv")
    sample = _rows(root / "sample_submission.csv")

    assert train and predict and sample
    assert "sales" in train[0]
    assert "sales" not in predict[0]
    assert [row["row_id"] for row in predict] == [row["row_id"] for row in sample]
    assert list(sample[0]) == ["row_id", "sales"]
