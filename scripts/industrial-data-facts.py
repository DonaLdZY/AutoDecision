"""Verify task-defining dates, labels and sample groups with bounded readers."""
from pathlib import Path
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT.parent / "AutoDecision_Sample"
OUT = ROOT / "runs/industrial-examples-20260907/inspection"


def main():
    facts = {}
    steel = pd.read_csv(SAMPLES / "steel+industry+energy+consumption/Steel_industry_data.csv")
    steel_times = pd.to_datetime(steel["date"], format="%d/%m/%Y %H:%M", errors="coerce")
    steel_target = pd.to_numeric(steel["Usage_kWh"], errors="coerce")
    intervals = steel_times.sort_values().diff().dropna()
    facts["steel"] = {
        "rows": len(steel), "invalid_timestamps": int(steel_times.isna().sum()),
        "duplicate_timestamps": int(steel_times.dropna().duplicated().sum()),
        "source_monotonic": steel_times.is_monotonic_increasing,
        "min_timestamp": steel_times.min(), "max_timestamp": steel_times.max(),
        "interval_counts_seconds": intervals.dt.total_seconds().value_counts().to_dict(),
        "invalid_targets": int((steel_target.isna() | steel_target.isin([float("inf"), float("-inf")])).sum()),
        "audit_scope": "full source table; model features, split purging and metrics require separate validation",
    }
    gantries, days = set(), {}
    path = next((SAMPLES / "车流预测").glob("*.csv"))
    for chunk in pd.read_csv(path, usecols=["门架id", "门架时间"], chunksize=100000):
        gantries.update(chunk["门架id"].unique())
        dates = pd.to_datetime(chunk["门架时间"], format="%d/%m/%Y %H:%M:%S").dt.strftime("%Y-%m-%d")
        for date, count in dates.value_counts().items():
            days[date] = days.get(date, 0) + int(count)
    facts["traffic"] = {"gantries": len(gantries), "daily_records": dict(sorted(days.items())), "day_first_verified": True}
    lab = pd.read_excel(SAMPLES / "化学工厂/浓度.xls")
    dates = pd.to_datetime(lab["采样时间"], errors="coerce")
    target = lab["参数"].astype(str).str.replace("）", ")").str.strip().str.lower().eq("al(n)") & lab["部位"].astype(str).str.contains("压滤液")
    target_times = dates[target]
    sensor_min, sensor_max = None, None
    for chunk in pd.read_csv(SAMPLES / "化学工厂/设备.csv", usecols=["SampleTime"], chunksize=100000):
        times = pd.to_datetime(chunk["SampleTime"], errors="coerce")
        sensor_min = times.min() if sensor_min is None else min(sensor_min, times.min())
        sensor_max = times.max() if sensor_max is None else max(sensor_max, times.max())
    facts["chemical"] = {"lab_rows": len(lab), "parameter_variants": list(lab["参数"].dropna().unique()),
        "outgoing_al_rows": int(target.sum()), "outgoing_al_timestamps": target_times.nunique(),
        "target_min": target_times.min(), "target_max": target_times.max(), "sensor_min": sensor_min, "sensor_max": sensor_max,
        "targets_with_sensor_time_overlap": int(target_times.between(sensor_min, sensor_max).sum())}
    capacity = pd.read_excel(SAMPLES / "城市配送智能/承运商每日可用车辆数据表.xlsx", sheet_name="Sheet1")
    facts["delivery"] = {"capacity_rows": len(capacity), "daily_capacity_rows": capacity["日期"].astype(str).value_counts().to_dict(),
        "carriers": capacity["承运商代码"].nunique(), "vehicle_type_counts": capacity["承运商车型"].value_counts().to_dict()}
    maintenance = pd.read_csv(SAMPLES / "ai4i+2020+predictive+maintenance+dataset/ai4i2020.csv")
    facts["ai4i"] = {"rows": len(maintenance), "failure_counts": maintenance["Machine failure"].value_counts().to_dict()}
    deposition = next(SAMPLES.glob("Data_for_*"))
    curves = []
    for path in sorted(deposition.rglob("Cooling_rates_*.csv")):
        frame = pd.read_csv(path, sep=";", encoding="cp1252", header=None, low_memory=False)
        zones = [column for column in range(frame.shape[1]) if isinstance(frame.iloc[0, column], str) and frame.iloc[0, column].strip()]
        lengths = {str(frame.iloc[0, column]): int(pd.to_numeric(frame.iloc[2:, column + 2], errors="coerce").notna().sum()) for column in zones}
        curves.append({"file": path.name, "zone_count": len(zones), "temperature_samples": sum(lengths.values()),
                       "curve_lengths_min": min(lengths.values()), "curve_lengths_max": max(lengths.values())})
    facts["deposition"] = curves
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "task-defining-facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(facts, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
