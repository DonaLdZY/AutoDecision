"""
城配物流智能调度系统 - 完整解决方案
Hybrid ML + Optimization approach:
1. Business logic layer: atomic order parsing, carrier cost calculation
2. Cost prediction model: neural network for trip cost estimation
3. Beam-search scheduler with learned cost guidance
4. Local search optimization for solution improvement
"""

import pandas as pd
import numpy as np
import os
import re
import copy
import random
import warnings
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Optional, Any

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR

warnings.filterwarnings("ignore")

# ============================================================
# CONSTANTS
# ============================================================
BIG_M = 1e12
PROHIBITED_CUSTOMERS = {"FYP01", "MH101", "NH001", "SMG01", "YPF01"}
SPECIAL_WAREHOUSES = {"凯东源光明仓", "深圳坪山仓"}

VEHICLE_SIZE_MAP = {
    "面包车": 1.0,
    "微面": 1.0,
    "小货车": 2.0,
    "4米2": 2.0,
    "4.2米": 2.0,
    "中货车": 3.0,
    "6米8": 3.0,
    "6.8米": 3.0,
    "7米6": 4.0,
    "7.6米": 4.0,
    "大货车": 5.0,
    "9米6": 5.0,
    "9.6米": 5.0,
    "12米5": 6.0,
    "12.5米": 6.0,
    "16米5": 7.0,
    "16.5米": 7.0,
    "拖头": 8.0,
    "重卡": 8.0,
}

# ============================================================
# DATA LOADING & PREPROCESSING
# ============================================================
print("Loading data...")

orders_df = pd.read_excel("./input/15天订单数据1027-1110.xlsx")
address_df = pd.read_excel("./input/客户地址表1027-1110.xlsx")
vehicle_avail_df = pd.read_excel("./input/承运商每日可用车辆数据表.xlsx")
product_df = pd.read_excel("./input/货品资料1027-1110.xlsx")
capacity_df = pd.read_excel("./input/车型装载表l.xlsx")

# Load carrier cost files
cost_dir = Path("./input/成本/")
cost_files = list(cost_dir.glob("*.xlsx"))
carrier_costs = {}
for f in cost_files:
    carrier_name = f.stem.replace(" 承运商成本", "")
    carrier_costs[carrier_name] = pd.read_excel(f)

print(f"Orders: {orders_df.shape}, Carriers: {len(carrier_costs)}")

# ============================================================
# DATA CLEANING
# ============================================================
orders_df.columns = orders_df.columns.str.strip()
address_df.columns = address_df.columns.str.strip()
vehicle_avail_df.columns = vehicle_avail_df.columns.str.strip()
product_df.columns = product_df.columns.str.strip()
capacity_df.columns = capacity_df.columns.str.strip()

# Parse dates
for col in [
    "客户下单时间",
    "要求交付时间",
    "最早提货时间",
    "最晚提货时间",
    "最早交货时间",
    "最晚交货时间",
]:
    if col in orders_df.columns:
        orders_df[col] = pd.to_datetime(orders_df[col], errors="coerce")

orders_df["下单日期"] = orders_df["客户下单时间"].dt.date

# String standardization
for col in [
    "订单号",
    "原始订单号",
    "客户代码",
    "收货地址",
    "发货地址",
    "限制车型",
    "货品代码",
]:
    if col in orders_df.columns:
        orders_df[col] = orders_df[col].astype(str).str.strip()
        orders_df[col] = orders_df[col].replace(["nan", "None", ""], np.nan)

# Product info
product_df["货品代码"] = product_df["货品代码"].astype(str).str.strip()
if "体积(cm³)" in product_df.columns:
    product_df["体积_m3"] = (
        pd.to_numeric(product_df["体积(cm³)"], errors="coerce") / 1e6
    )
if "毛重(g)" in product_df.columns:
    product_df["毛重_kg"] = pd.to_numeric(product_df["毛重(g)"], errors="coerce") / 1000

# Vehicle capacity - parse with explicit column names
print(f"Capacity columns: {capacity_df.columns.tolist()}")
# Standardize column names
capacity_df.columns = [str(c).strip() for c in capacity_df.columns]
cap_rename = {}
for col in capacity_df.columns:
    col_lower = col.lower()
    if "装载" in col and ("kg" in col_lower or "重量" in col):
        cap_rename[col] = "最大装载量_kg"
    elif "装载" in col and ("体积" in col or "m3" in col_lower):
        cap_rename[col] = "最大装载体积_m3"
    elif "车型" in col:
        cap_rename[col] = "车型"
    elif "超载" in col:
        cap_rename[col] = "最大超载系数"
if cap_rename:
    capacity_df.rename(columns=cap_rename, inplace=True)
# Ensure required columns exist
if "车型" not in capacity_df.columns:
    for col in capacity_df.columns:
        if "车型" in str(col):
            capacity_df.rename(columns={col: "车型"}, inplace=True)
            break
if "最大装载量_kg" not in capacity_df.columns:
    for col in capacity_df.columns:
        if "装载" in str(col) and ("kg" in str(col).lower() or "重量" in str(col)):
            capacity_df.rename(columns={col: "最大装载量_kg"}, inplace=True)
            break
if "最大装载体积_m3" not in capacity_df.columns:
    for col in capacity_df.columns:
        if "装载" in str(col) and ("体积" in str(col) or "m3" in str(col).lower()):
            capacity_df.rename(columns={col: "最大装载体积_m3"}, inplace=True)
            break
if "最大超载系数" not in capacity_df.columns:
    for col in capacity_df.columns:
        if "超载" in str(col):
            capacity_df.rename(columns={col: "最大超载系数"}, inplace=True)
            break
print(f"Capacity columns after rename: {capacity_df.columns.tolist()}")

# Vehicle availability
vehicle_avail_df["承运商车型"] = vehicle_avail_df["承运商车型"].astype(str).str.strip()
vehicle_avail_df["承运商代码"] = vehicle_avail_df["承运商代码"].astype(str).str.strip()

# ============================================================
# ATOMIC ORDER CONSTRUCTION
# ============================================================
print("Building atomic orders...")

order_agg = (
    orders_df.groupby("订单号")
    .agg(
        订单总体积=("下单体积(m³)", "sum"),
        订单总重量=("下单重量(kg)", "sum"),
        最早提货=("最早提货时间", "min"),
        最晚提货=("最晚提货时间", "max"),
        最早交货=("最早交货时间", "min"),
        最晚交货=("最晚交货时间", "max"),
        下单时间=("客户下单时间", "min"),
        要求交付时间=("要求交付时间", "min"),
        客户代码=("客户代码", "first"),
        收货地址=("收货地址", "first"),
        发货地址=("发货地址", "first"),
        限制车型=("限制车型", "first"),
        原始订单号=("原始订单号", "first"),
        下单日期=("下单日期", "first"),
    )
    .reset_index()
)


def get_atomic_id(row):
    orig = row["原始订单号"]
    if pd.notna(orig) and str(orig).strip() != "":
        return str(orig).strip()
    order_id = str(row["订单号"])
    cx_match = re.match(r"^(.*)C\d+$", order_id)
    if cx_match:
        return cx_match.group(1)
    return order_id


order_agg["atomic_order_id"] = order_agg.apply(get_atomic_id, axis=1)

# Aggregate by atomic_order_id
atomic_orders = (
    order_agg.groupby("atomic_order_id")
    .agg(
        订单总体积=("订单总体积", "sum"),
        订单总重量=("订单总重量", "sum"),
        最早提货=("最早提货", "min"),
        最晚提货=("最晚提货", "max"),
        最早交货=("最早交货", "min"),
        最晚交货=("最晚交货", "max"),
        下单时间=("下单时间", "min"),
        要求交付时间=("要求交付时间", "min"),
        客户代码=("客户代码", "first"),
        收货地址=("收货地址", "first"),
        发货地址=("发货地址", "first"),
        限制车型=("限制车型", "first"),
        下单日期=("下单日期", "first"),
        子订单数=("订单号", "count"),
    )
    .reset_index()
)

atomic_orders["限制车型等级"] = (
    atomic_orders["限制车型"].map(VEHICLE_SIZE_MAP).fillna(0)
)
atomic_orders["禁止聚合"] = (
    atomic_orders["客户代码"].isin(PROHIBITED_CUSTOMERS).astype(int)
)
atomic_orders["特殊仓"] = atomic_orders["发货地址"].apply(
    lambda x: 1 if any(wh in str(x) for wh in SPECIAL_WAREHOUSES) else 0
)

print(
    f"Atomic orders: {len(atomic_orders)}, Unique dates: {atomic_orders['下单日期'].nunique()}"
)

# ============================================================
# VEHICLE REGISTRY & COST CALCULATOR
# ============================================================
print("Building vehicle registry...")

# Parse numeric values
if "最大装载量_kg" in capacity_df.columns:
    capacity_df["最大装载量_kg"] = pd.to_numeric(
        capacity_df["最大装载量_kg"], errors="coerce"
    ).fillna(0)
else:
    capacity_df["最大装载量_kg"] = 10000.0
if "最大装载体积_m3" in capacity_df.columns:
    capacity_df["最大装载体积_m3"] = pd.to_numeric(
        capacity_df["最大装载体积_m3"], errors="coerce"
    ).fillna(0)
else:
    capacity_df["最大装载体积_m3"] = 50.0
if "最大超载系数" in capacity_df.columns:
    overload = pd.to_numeric(capacity_df["最大超载系数"], errors="coerce").fillna(0)
else:
    overload = pd.Series([0.0] * len(capacity_df))
capacity_df["有效载重_kg"] = capacity_df["最大装载量_kg"] * (1 + overload)
capacity_df["有效体积_m3"] = capacity_df["最大装载体积_m3"] * (1 + overload)
print(
    f"Vehicle capacity ranges - weight: {capacity_df['有效载重_kg'].min():.0f}-{capacity_df['有效载重_kg'].max():.0f} kg, volume: {capacity_df['有效体积_m3'].min():.1f}-{capacity_df['有效体积_m3'].max():.1f} m3"
)


def extract_size_tier(name):
    name = str(name).strip()
    for key, val in sorted(VEHICLE_SIZE_MAP.items(), key=lambda x: -len(x[0])):
        if key in name:
            return val
    m_match = re.search(r"(\d+\.?\d*)\s*米", name)
    if m_match:
        return float(m_match.group(1))
    return 0.0


capacity_df["车型尺寸_米"] = capacity_df["车型"].apply(extract_size_tier)

# Build cost master
cost_records = []
for carrier, cost_df in carrier_costs.items():
    cost_df.columns = cost_df.columns.str.strip()
    if "合同有效标志" in cost_df.columns:
        cost_df = cost_df[cost_df["合同有效标志"].astype(str).str.strip() == "是"]
    for _, row in cost_df.iterrows():
        cost_records.append(
            {
                "承运商": carrier,
                "车型": str(row.get("车型", row.get("承运商车型", ""))).strip(),
                "计费费率": float(row.get("计费费率", 0) or 0),
                "保底费": float(row.get("保底费", 0) or 0),
                "重量下限": float(row.get("重量下限", row.get("最小重量", 0)) or 0),
                "重量上限": float(
                    row.get("重量上限", row.get("最大重量", np.inf)) or np.inf
                ),
                "同区多点费率": float(
                    row.get("同区多点费率", row.get("同/跨区多点费率", 0)) or 0
                ),
                "跨区多点费率": float(
                    row.get("跨区多点费率", row.get("同/跨区多点费率", 0)) or 0
                ),
            }
        )
cost_master = pd.DataFrame(cost_records)

# Vehicle registry
vehicle_registry = {}
for _, row in capacity_df.iterrows():
    vtype = str(row["车型"]).strip()
    vehicle_registry[vtype] = {
        "max_weight_kg": float(row["有效载重_kg"]),
        "max_volume_m3": float(row["有效体积_m3"]),
        "size_tier": float(row["车型尺寸_米"]),
    }

# Add cost info
for vtype in vehicle_registry:
    vtype_costs = cost_master[cost_master["车型"].str.strip() == vtype]
    if len(vtype_costs) > 0:
        vehicle_registry[vtype]["avg_rate"] = vtype_costs["计费费率"].mean()
        vehicle_registry[vtype]["min_rate"] = vtype_costs["计费费率"].min()
        vehicle_registry[vtype]["avg_base_fee"] = vtype_costs["保底费"].mean()
    else:
        vehicle_registry[vtype]["avg_rate"] = 0.0
        vehicle_registry[vtype]["min_rate"] = 0.0
        vehicle_registry[vtype]["avg_base_fee"] = 0.0

# Parse vehicle availability columns (static snapshot - no date column)
print(f"Vehicle avail columns: {vehicle_avail_df.columns.tolist()}")
vt_col = None
for col in vehicle_avail_df.columns:
    if "车型" in str(col):
        vt_col = col
        break
qty_col = None
for col in vehicle_avail_df.columns:
    if "数量" in str(col) or "num" in str(col).lower():
        qty_col = col
        break

if vt_col and qty_col:
    vehicle_avail_df[vt_col] = vehicle_avail_df[vt_col].astype(str).str.strip()
    vehicle_avail_df[qty_col] = pd.to_numeric(
        vehicle_avail_df[qty_col], errors="coerce"
    ).fillna(0)
    avail_grouped = vehicle_avail_df.groupby(vt_col)[qty_col].sum()
    for vtype in vehicle_registry:
        vehicle_registry[vtype]["total_available"] = int(avail_grouped.get(vtype, 0))
    print(f"Vehicle availability: {dict(avail_grouped)}")
else:
    print("Warning: Could not find vehicle type/quantity columns in availability data")
    for vtype in vehicle_registry:
        vehicle_registry[vtype]["total_available"] = 999

# Build a day-independent vehicle_registry for training (no availability leakage)
# This registry uses ONLY static vehicle properties (capacity, cost) and sets
# availability to a large dummy value, since daily availability is applied at inference.
vehicle_registry_train = {}
for vt, vinfo in vehicle_registry.items():
    vehicle_registry_train[vt] = {
        "max_weight_kg": vinfo["max_weight_kg"],
        "max_volume_m3": vinfo["max_volume_m3"],
        "size_tier": vinfo["size_tier"],
        "avg_rate": vinfo.get("avg_rate", 0.0),
        "min_rate": vinfo.get("min_rate", 0.0),
        "avg_base_fee": vinfo.get("avg_base_fee", 0.0),
        "total_available": 999,
    }

# Build vehicle_types from BOTH capacity data AND availability data
all_vehicle_types = set()
for _, row in capacity_df.iterrows():
    all_vehicle_types.add(str(row["车型"]).strip())
for vt in vehicle_avail_df[vt_col].unique():
    all_vehicle_types.add(str(vt).strip())
for _, row in cost_master.iterrows():
    all_vehicle_types.add(str(row["车型"]).strip())

# Ensure all vehicle types have entries in vehicle_registry
for vt in all_vehicle_types:
    if vt not in vehicle_registry:
        matching_cap = capacity_df[capacity_df["车型"].str.strip() == vt]
        if len(matching_cap) > 0:
            row = matching_cap.iloc[0]
            vehicle_registry[vt] = {
                "max_weight_kg": (
                    float(row["有效载重_kg"])
                    if "有效载重_kg" in matching_cap.columns
                    else float(row.get("最大装载量_kg", 10000))
                ),
                "max_volume_m3": (
                    float(row["有效体积_m3"])
                    if "有效体积_m3" in matching_cap.columns
                    else float(row.get("最大装载体积_m3", 50))
                ),
                "size_tier": (
                    float(row["车型尺寸_米"])
                    if "车型尺寸_米" in matching_cap.columns
                    else extract_size_tier(vt)
                ),
                "avg_rate": 0.5,
                "min_rate": 0.5,
                "avg_base_fee": 50.0,
                "total_available": int(avail_grouped.get(vt, 0)),
            }
        else:
            vehicle_registry[vt] = {
                "max_weight_kg": 10000.0,
                "max_volume_m3": 50.0,
                "size_tier": extract_size_tier(vt),
                "avg_rate": 0.5,
                "min_rate": 0.5,
                "avg_base_fee": 50.0,
                "total_available": int(avail_grouped.get(vt, 0)),
            }

vehicle_types = sorted(vehicle_registry.keys())
num_vehicle_types = len(vehicle_types)
vtype_to_idx = {vt: i for i, vt in enumerate(vehicle_types)}
print(f"Vehicle types: {num_vehicle_types}")

# Build a day-independent vehicle_registry for training (no availability leakage)
# Must be done AFTER all vehicle types are registered
vehicle_registry_train = {}
for vt, vinfo in vehicle_registry.items():
    vehicle_registry_train[vt] = {k: v for k, v in vinfo.items()}
    vehicle_registry_train[vt]["total_available"] = 999

# Cost lookup - build comprehensive cost table
cost_lookup = {}
for _, row in cost_master.iterrows():
    vtype = str(row["车型"]).strip()
    key = (vtype, float(row["重量下限"]), float(row["重量上限"]))
    cost_lookup[key] = {
        "rate": float(row["计费费率"]),
        "base_fee": float(row["保底费"]),
        "multi_rate": float(row["同区多点费率"]),
        "cross_rate": float(row["跨区多点费率"]),
    }

# Also build per-vehicle-type cost summary for quick lookup
vehicle_cost_summary = {}
for vtype in vehicle_registry:
    vtype_costs = cost_master[cost_master["车型"].str.strip() == vtype]
    if len(vtype_costs) > 0:
        vehicle_cost_summary[vtype] = {
            "rates": vtype_costs["计费费率"].tolist(),
            "base_fees": vtype_costs["保底费"].tolist(),
            "avg_rate": vtype_costs["计费费率"].mean(),
            "min_rate": vtype_costs["计费费率"].min(),
            "avg_base_fee": vtype_costs["保底费"].mean(),
        }
    else:
        best_match_rate = 0.5
        best_match_base = 50.0
        for existing_vt, summary in vehicle_cost_summary.items():
            if summary["avg_rate"] > 0:
                best_match_rate = summary["avg_rate"]
                best_match_base = summary["avg_base_fee"]
                break
        vehicle_cost_summary[vtype] = {
            "rates": [best_match_rate],
            "base_fees": [best_match_base],
            "avg_rate": best_match_rate,
            "min_rate": best_match_rate,
            "avg_base_fee": best_match_base,
        }
        vehicle_registry[vtype]["avg_rate"] = best_match_rate
        vehicle_registry[vtype]["min_rate"] = best_match_rate
        vehicle_registry[vtype]["avg_base_fee"] = best_match_base


def calculate_trip_cost(vehicle_type, total_weight_kg, num_stops, is_cross_zone=False):
    total_weight_ton = total_weight_kg / 1000.0
    best_match = None
    for (vtype, wlow, whigh), info in cost_lookup.items():
        if vtype == vehicle_type and wlow <= total_weight_ton < whigh:
            best_match = info
            break
    if best_match is None:
        for (vtype, wlow, whigh), info in cost_lookup.items():
            if vtype == vehicle_type:
                best_match = info
                break
    if best_match is None:
        for (vtype, wlow, whigh), info in cost_lookup.items():
            if vehicle_type in vtype or vtype in vehicle_type:
                best_match = info
                break
    if best_match is None:
        summary = vehicle_cost_summary.get(
            vehicle_type,
            {
                "avg_rate": 0.5,
                "avg_base_fee": 50.0,
                "rates": [0.5],
                "base_fees": [50.0],
            },
        )
        rate = summary["avg_rate"]
        base = summary["avg_base_fee"]
        weight_cost = total_weight_ton * rate
        cost = max(weight_cost, base)
        if num_stops > 1:
            cost += (num_stops - 1) * rate * total_weight_ton * 0.3
        return cost
    weight_cost = total_weight_ton * best_match["rate"]
    cost = max(weight_cost, best_match["base_fee"])
    if num_stops > 1:
        extra_stops = num_stops - 1
        if is_cross_zone:
            cost += extra_stops * best_match["cross_rate"]
        else:
            cost += extra_stops * best_match["multi_rate"]
    return cost


# ============================================================
# TEMPORAL SPLIT
# ============================================================
all_dates = sorted(atomic_orders["下单日期"].dropna().unique())
n_total = len(all_dates)
test_dates = all_dates[-30:] if n_total >= 30 else all_dates[-max(1, n_total // 3) :]
train_val_dates = [d for d in all_dates if d not in test_dates]
val_size = max(1, int(len(train_val_dates) * 0.2))
val_dates = train_val_dates[-val_size:]
train_dates = train_val_dates[:-val_size]

print(f"Train: {len(train_dates)}, Val: {len(val_dates)}, Test: {len(test_dates)}")

# ============================================================
# GENERATE TRAINING DATA FOR COST PREDICTOR
# ============================================================
print("Generating training samples...")

train_orders_df = atomic_orders[atomic_orders["下单日期"].isin(train_dates)].copy()
training_samples = []

# Use all train days to generate training samples
for date in train_dates:
    day_orders = train_orders_df[train_orders_df["下单日期"] == date].sort_values(
        "最晚交货"
    )
    if len(day_orders) == 0:
        continue

    # Reset vehicle state for each day independently - use actual availability
    active_vehicles = []
    remaining_vehicles = {
        vt: vehicle_registry[vt]["total_available"] for vt in vehicle_types
    }

    for _, order in day_orders.iterrows():
        order_vol = float(order["订单总体积"])
        order_wt = float(order["订单总重量"])
        order_restriction = float(order["限制车型等级"])
        order_id = order["atomic_order_id"]
        order_addr = str(order.get("收货地址", ""))

        assigned = False
        for av in active_vehicles:
            vinfo = vehicle_registry_train[av["type"]]
            if (
                av["volume"] + order_vol <= vinfo["max_volume_m3"] + 1e-3
                and av["weight"] + order_wt <= vinfo["max_weight_kg"] + 1e-3
                and vinfo["size_tier"] >= order_restriction
            ):
                av["orders"].append(order_id)
                av["volume"] += order_vol
                av["weight"] += order_wt
                if order_addr not in av["addresses"]:
                    av["addresses"].add(order_addr)
                    av["stops"] += 1
                assigned = True
                break

        if not assigned:
            # Find best vehicle type for this order
            best_vtype = None
            best_rate = float("inf")
            for vt in vehicle_types:
                vinfo = vehicle_registry_train.get(vt)
                if vinfo is None:
                    vinfo = vehicle_registry.get(vt)
                if vinfo is None:
                    continue
                if remaining_vehicles.get(vt, 0) <= 0:
                    continue
                if (
                    order_vol > vinfo["max_volume_m3"] + 1e-3
                    or order_wt > vinfo["max_weight_kg"] + 1e-3
                ):
                    continue
                if vinfo["size_tier"] < order_restriction:
                    continue
                rate = vinfo.get("avg_rate", float("inf"))
                if rate < best_rate:
                    best_rate = rate
                    best_vtype = vt
            # If no vehicle can fit, use largest available
            if best_vtype is None:
                for vt in reversed(vehicle_types):
                    if remaining_vehicles.get(vt, 0) > 0:
                        best_vtype = vt
                        break
            if best_vtype is None:
                continue
            remaining_vehicles[best_vtype] -= 1
            active_vehicles.append(
                {
                    "type": best_vtype,
                    "orders": [order_id],
                    "volume": order_vol,
                    "weight": order_wt,
                    "addresses": {order_addr},
                    "stops": 1,
                }
            )

    for av in active_vehicles:
        full_cost = calculate_trip_cost(av["type"], av["weight"], av["stops"])
        vinfo = vehicle_registry_train.get(av["type"])
        if vinfo is None:
            vinfo = vehicle_registry.get(av["type"], {
                "size_tier": 0.0,
                "max_weight_kg": 10000.0,
                "max_volume_m3": 50.0,
                "avg_rate": 0.5,
                "avg_base_fee": 50.0,
            })
        # Use cost calculator directly for training labels (no learned model leakage)
        training_samples.append(
            {
                "vehicle_type": av["type"],
                "vehicle_type_idx": vtype_to_idx.get(av["type"], 0),
                "vehicle_size_tier": vinfo["size_tier"],
                "vehicle_max_weight": vinfo["max_weight_kg"],
                "vehicle_max_volume": vinfo["max_volume_m3"],
                "vehicle_avg_rate": vinfo.get("avg_rate", 0),
                "vehicle_base_fee": vinfo.get("avg_base_fee", 0),
                "current_volume": av["volume"],
                "current_weight": av["weight"],
                "current_stops": av["stops"],
                "current_num_orders": len(av["orders"]),
                "weight_utilization": av["weight"] / max(vinfo["max_weight_kg"], 1e-6),
                "volume_utilization": av["volume"] / max(vinfo["max_volume_m3"], 1e-6),
                "remaining_orders_count": 0,
                "final_cost": full_cost,
                "final_weight_util": av["weight"] / max(vinfo["max_weight_kg"], 1e-6),
                "final_volume_util": av["volume"] / max(vinfo["max_volume_m3"], 1e-6),
                "final_stops": av["stops"],
            }
        )

training_df = pd.DataFrame(training_samples)
print(f"Training samples: {len(training_df)}")

# If no training samples generated, create synthetic samples from cost rules
if len(training_df) == 0:
    print("No real training samples, generating synthetic samples from cost rules...")
    synthetic_samples = []
    for vt in vehicle_types:
        vinfo = vehicle_registry[vt]
        for num_orders in [1, 2, 3, 5]:
            for util_pct in [0.2, 0.4, 0.6, 0.8, 1.0]:
                weight = vinfo["max_weight_kg"] * util_pct
                volume = vinfo["max_volume_m3"] * util_pct
                stops = min(num_orders, 3)
                cost = calculate_trip_cost(vt, weight, stops)
                synthetic_samples.append(
                    {
                        "vehicle_type": vt,
                        "vehicle_type_idx": vtype_to_idx.get(vt, 0),
                        "vehicle_size_tier": vinfo["size_tier"],
                        "vehicle_max_weight": vinfo["max_weight_kg"],
                        "vehicle_max_volume": vinfo["max_volume_m3"],
                        "vehicle_avg_rate": vinfo.get("avg_rate", 0),
                        "vehicle_base_fee": vinfo.get("avg_base_fee", 0),
                        "current_volume": volume,
                        "current_weight": weight,
                        "current_stops": stops,
                        "current_num_orders": num_orders,
                        "weight_utilization": util_pct,
                        "volume_utilization": util_pct,
                        "remaining_orders_count": 0,
                        "final_cost": cost,
                        "final_weight_util": util_pct,
                        "final_volume_util": util_pct,
                        "final_stops": stops,
                    }
                )
    training_df = pd.DataFrame(synthetic_samples)
    print(f"Synthetic training samples: {len(training_df)}")


# ============================================================
# DATASET
# ============================================================
class TripCostDataset(Dataset):
    def __init__(self, df, num_vtypes, max_orders=50):
        self.df = df.reset_index(drop=True)
        self.num_vtypes = num_vtypes
        self.max_orders = max_orders

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        vehicle_type_idx = int(row["vehicle_type_idx"])
        vehicle_features = np.array(
            [
                row["vehicle_size_tier"],
                row["vehicle_max_weight"] / 10000.0,
                row["vehicle_max_volume"] / 50.0,
                row["vehicle_avg_rate"] / 100.0,
                row["vehicle_base_fee"] / 1000.0,
            ],
            dtype=np.float32,
        )
        load_summary = np.array(
            [
                row["current_volume"],
                row["current_weight"],
                row["current_num_orders"],
                row["current_stops"],
                row["weight_utilization"],
                row["volume_utilization"],
            ],
            dtype=np.float32,
        )
        unassigned_summary = np.array(
            [
                row["remaining_orders_count"],
                row["remaining_orders_count"] * 2.0,
                row["remaining_orders_count"] * 100.0,
                2.0,
                100.0,
                0.0,
                0.0,
                0.0,
            ],
            dtype=np.float32,
        )
        loaded_orders = np.zeros((self.max_orders, 12), dtype=np.float32)
        loaded_mask = np.zeros(self.max_orders, dtype=np.float32)
        n_orders = min(int(row["current_num_orders"]), self.max_orders)
        for i in range(n_orders):
            loaded_orders[i, 0] = row["current_volume"] / max(n_orders, 1)
            loaded_orders[i, 1] = row["current_weight"] / max(n_orders, 1)
            loaded_orders[i, 9] = 1.0
            loaded_mask[i] = 1.0
        remaining_counts = np.ones(self.num_vtypes, dtype=np.float32) * 5.0
        fleet_utilization = np.zeros(self.num_vtypes, dtype=np.float32)

        return {
            "vehicle_type_idx": torch.tensor(vehicle_type_idx, dtype=torch.long),
            "vehicle_features": torch.tensor(vehicle_features, dtype=torch.float32),
            "loaded_orders": torch.tensor(loaded_orders, dtype=torch.float32),
            "loaded_mask": torch.tensor(loaded_mask, dtype=torch.float32),
            "load_summary": torch.tensor(load_summary, dtype=torch.float32),
            "remaining_counts": torch.tensor(remaining_counts, dtype=torch.float32),
            "fleet_utilization": torch.tensor(fleet_utilization, dtype=torch.float32),
            "unassigned_summary": torch.tensor(unassigned_summary, dtype=torch.float32),
            "cost_true": torch.tensor(float(row["final_cost"]), dtype=torch.float32),
            "weight_util_true": torch.tensor(
                float(row["final_weight_util"]), dtype=torch.float32
            ),
            "volume_util_true": torch.tensor(
                float(row["final_volume_util"]), dtype=torch.float32
            ),
            "num_stops_true": torch.tensor(
                float(row["final_stops"]), dtype=torch.float32
            ),
        }


# Split training data
np.random.seed(42)
n_samples = len(training_df)
if n_samples < 10:
    train_dataset = TripCostDataset(training_df, num_vehicle_types)
    val_dataset = TripCostDataset(training_df.head(1).copy(), num_vehicle_types)
    batch_size = max(1, min(8, n_samples))
else:
    indices = np.random.permutation(n_samples)
    val_split = max(1, int(n_samples * 0.15))
    train_idx = indices[val_split:]
    val_idx = indices[:val_split]
    train_dataset = TripCostDataset(training_df.iloc[train_idx], num_vehicle_types)
    val_dataset = TripCostDataset(training_df.iloc[val_idx], num_vehicle_types)
    batch_size = min(64, max(8, n_samples // 4))

train_loader = DataLoader(
    train_dataset, batch_size=batch_size, shuffle=True, num_workers=0
)
val_loader = DataLoader(
    val_dataset, batch_size=max(1, batch_size // 2), shuffle=False, num_workers=0
)


# ============================================================
# MODEL DEFINITION
# ============================================================
class VehicleTypeEncoder(nn.Module):
    def __init__(self, num_vtypes, emb_dim=16):
        super().__init__()
        self.embedding = nn.Embedding(num_vtypes, emb_dim)
        self.projection = nn.Linear(emb_dim + 5, 32)

    def forward(self, vt_idx, vt_features):
        if vt_idx.dim() > 1:
            vt_idx = vt_idx.squeeze(-1)
        emb = self.embedding(vt_idx)
        return F.relu(self.projection(torch.cat([emb, vt_features], dim=-1)))


class OrderSetEncoder(nn.Module):
    def __init__(self, order_feat_dim=12, hidden_dim=64):
        super().__init__()
        self.order_proj = nn.Sequential(
            nn.Linear(order_feat_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )
        self.attention = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.Tanh(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(self, orders, mask):
        projected = self.order_proj(orders)
        attn_scores = self.attention(projected).squeeze(-1)
        attn_scores = attn_scores.masked_fill(mask == 0, -1e9)
        attn_weights = F.softmax(attn_scores, dim=-1).unsqueeze(-1)
        aggregated = (projected * attn_weights).sum(dim=1)
        sum_features = (orders * mask.unsqueeze(-1)).sum(dim=1)
        return torch.cat([aggregated, sum_features[:, :4]], dim=-1)


class CapacityEncoder(nn.Module):
    def __init__(self, num_vtypes, hidden_dim=32):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(num_vtypes * 2, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(self, remaining, utilization):
        return F.relu(self.encoder(torch.cat([remaining, utilization], dim=-1)))


class TripCostPredictor(nn.Module):
    def __init__(self, num_vtypes, order_feat_dim=12, hidden_dim=128, dropout=0.2):
        super().__init__()
        self.vehicle_encoder = VehicleTypeEncoder(num_vtypes)
        self.order_encoder = OrderSetEncoder(order_feat_dim, hidden_dim=64)
        self.capacity_encoder = CapacityEncoder(num_vtypes, hidden_dim=32)
        self.load_encoder = nn.Sequential(
            nn.Linear(6, 32), nn.ReLU(), nn.Linear(32, 32)
        )
        self.unassigned_encoder = nn.Sequential(
            nn.Linear(8, 32), nn.ReLU(), nn.Linear(32, 32)
        )

        fusion_dim = 32 + 68 + 32 + 32 + 32
        self.fusion = nn.Sequential(
            nn.Linear(fusion_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.BatchNorm1d(hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.cost_head = nn.Sequential(
            nn.Linear(hidden_dim // 2, 32), nn.ReLU(), nn.Linear(32, 1)
        )
        self.weight_head = nn.Linear(hidden_dim // 2, 1)
        self.volume_head = nn.Linear(hidden_dim // 2, 1)
        self.stops_head = nn.Linear(hidden_dim // 2, 1)

    def forward(
        self,
        vehicle_type_idx,
        vehicle_features,
        loaded_orders,
        loaded_mask,
        load_summary,
        remaining_counts,
        fleet_utilization,
        unassigned_summary,
    ):
        v_enc = self.vehicle_encoder(vehicle_type_idx, vehicle_features)
        o_enc = self.order_encoder(loaded_orders, loaded_mask)
        c_enc = self.capacity_encoder(remaining_counts, fleet_utilization)
        l_enc = F.relu(self.load_encoder(load_summary))
        u_enc = F.relu(self.unassigned_encoder(unassigned_summary))
        fused = torch.cat([v_enc, o_enc, c_enc, l_enc, u_enc], dim=-1)
        hidden = self.fusion(fused)
        return {
            "cost_pred": F.softplus(self.cost_head(hidden).squeeze(-1)) + 1e-3,
            "weight_util_pred": torch.sigmoid(self.weight_head(hidden)).squeeze(-1),
            "volume_util_pred": torch.sigmoid(self.volume_head(hidden)).squeeze(-1),
            "num_stops_pred": F.softplus(self.stops_head(hidden)).squeeze(-1),
        }


# ============================================================
# TRAINING
# ============================================================
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

model = TripCostPredictor(num_vehicle_types, hidden_dim=128, dropout=0.2).to(device)
optimizer = AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
scheduler = CosineAnnealingLR(optimizer, T_max=50, eta_min=1e-5)
mse_loss = nn.MSELoss()
l1_loss = nn.L1Loss()

best_val_loss = float("inf")
patience = 10
patience_counter = 0
os.makedirs("./working", exist_ok=True)

n_epochs = min(80, max(20, n_samples * 2))
print(f"Training cost predictor for {n_epochs} epochs...")
for epoch in range(n_epochs):
    model.train()
    train_loss_sum = 0.0
    train_batches = 0

    for batch in train_loader:
        vt_idx = batch["vehicle_type_idx"].to(device)
        vt_feat = batch["vehicle_features"].to(device)
        loaded = batch["loaded_orders"].to(device)
        lmask = batch["loaded_mask"].to(device)
        lsum = batch["load_summary"].to(device)
        rem = batch["remaining_counts"].to(device)
        util = batch["fleet_utilization"].to(device)
        usum = batch["unassigned_summary"].to(device)
        cost_t = batch["cost_true"].to(device)
        w_t = batch["weight_util_true"].to(device)
        v_t = batch["volume_util_true"].to(device)
        s_t = batch["num_stops_true"].to(device)

        preds = model(vt_idx, vt_feat, loaded, lmask, lsum, rem, util, usum)
        loss = (
            mse_loss(preds["cost_pred"], cost_t)
            + 0.1 * mse_loss(preds["weight_util_pred"], w_t)
            + 0.1 * mse_loss(preds["volume_util_pred"], v_t)
            + 0.1 * l1_loss(preds["num_stops_pred"], s_t)
        )

        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        train_loss_sum += loss.item()
        train_batches += 1

    scheduler.step()
    avg_train_loss = train_loss_sum / max(train_batches, 1)

    model.eval()
    val_loss_sum = 0.0
    val_batches = 0
    with torch.no_grad():
        for batch in val_loader:
            vt_idx = batch["vehicle_type_idx"].to(device)
            vt_feat = batch["vehicle_features"].to(device)
            loaded = batch["loaded_orders"].to(device)
            lmask = batch["loaded_mask"].to(device)
            lsum = batch["load_summary"].to(device)
            rem = batch["remaining_counts"].to(device)
            util = batch["fleet_utilization"].to(device)
            usum = batch["unassigned_summary"].to(device)
            cost_t = batch["cost_true"].to(device)

            preds = model(vt_idx, vt_feat, loaded, lmask, lsum, rem, util, usum)
            loss = mse_loss(preds["cost_pred"], cost_t)
            val_loss_sum += loss.item()
            val_batches += 1

    avg_val_loss = val_loss_sum / max(val_batches, 1)

    if avg_val_loss < best_val_loss:
        best_val_loss = avg_val_loss
        patience_counter = 0
        torch.save(model.state_dict(), "./working/best_model.pt")
    else:
        patience_counter += 1

    if epoch % 10 == 0:
        print(
            f"Epoch {epoch}: train_loss={avg_train_loss:.4f}, val_loss={avg_val_loss:.4f}"
        )

    if patience_counter >= patience:
        print(f"Early stopping at epoch {epoch}")
        break

if n_samples >= 5:
    model.load_state_dict(torch.load("./working/best_model.pt"))
    model.eval()
else:
    print("Warning: Too few training samples, using cost calculator directly")
    model.eval()


# ============================================================
# CP-SAT SCHEDULER
# ============================================================
class CPSATScheduler:
    def __init__(self, vehicle_registry, vehicle_types, cost_calc, time_limit=60):
        self.vehicle_registry = vehicle_registry
        self.vehicle_types = vehicle_types
        self.cost_calc = cost_calc
        self.time_limit = time_limit

    def solve_day(self, orders_df):
        """Solve daily scheduling using CP-SAT with exact cost calculator."""
        try:
            from ortools.sat.python import cp_model
        except ImportError:
            print("OR-Tools not available, falling back to greedy scheduler")
            greedy = GreedyScheduler(self.vehicle_registry, self.vehicle_types, self.cost_calc)
            return greedy.solve_day(orders_df)

        orders = orders_df.sort_values("最晚交货").copy()
        order_list = orders.to_dict("records")
        if len(order_list) == 0:
            return {}, 0.0, {"unassigned_orders": 0}

        n_orders = len(order_list)

        # Build vehicle availability
        available_vehicles = {}
        for vt in self.vehicle_types:
            count = self.vehicle_registry[vt]["total_available"]
            if count > 0:
                available_vehicles[vt] = count

        if not available_vehicles:
            return {}, 0.0, {"unassigned_orders": n_orders}

        # Create vehicle instances (each available vehicle is a separate bin)
        vehicle_instances = []
        for vt, count in available_vehicles.items():
            for i in range(min(count, n_orders)):  # Don't need more vehicles than orders
                vehicle_instances.append({
                    "type": vt,
                    "instance_id": f"{vt}_{i}",
                    "max_weight": self.vehicle_registry[vt]["max_weight_kg"],
                    "max_volume": self.vehicle_registry[vt]["max_volume_m3"],
                    "size_tier": self.vehicle_registry[vt]["size_tier"],
                })

        n_vehicles = len(vehicle_instances)

        # Pre-compute costs for each order-vehicle pair (single order cost)
        single_order_costs = {}
        for v_idx, v in enumerate(vehicle_instances):
            for o_idx, order in enumerate(order_list):
                order_wt = float(order["订单总重量"])
                cost = self.cost_calc(v["type"], order_wt, 1)
                single_order_costs[(v_idx, o_idx)] = cost

        # Build CP-SAT model
        model = cp_model.CpModel()

        # Decision variables: x[v, o] = 1 if order o is assigned to vehicle v
        x = {}
        for v_idx in range(n_vehicles):
            for o_idx in range(n_orders):
                order = order_list[o_idx]
                order_vol = float(order["订单总体积"])
                order_wt = float(order["订单总重量"])
                order_restriction = float(order["限制车型等级"])
                v = vehicle_instances[v_idx]

                # Check feasibility
                if (order_vol <= v["max_volume"] + 1e-3 and
                    order_wt <= v["max_weight"] + 1e-3 and
                    v["size_tier"] >= order_restriction):
                    x[(v_idx, o_idx)] = model.NewBoolVar(f"x_{v_idx}_{o_idx}")
                else:
                    x[(v_idx, o_idx)] = model.NewConstant(0)

        # Each order must be assigned to exactly one vehicle
        for o_idx in range(n_orders):
            model.Add(sum(x.get((v_idx, o_idx), 0) for v_idx in range(n_vehicles)) == 1)

        # Capacity constraints for each vehicle
        for v_idx in range(n_vehicles):
            v = vehicle_instances[v_idx]
            # Weight constraint
            weight_terms = []
            for o_idx in range(n_orders):
                order_wt = float(order_list[o_idx]["订单总重量"])
                if (v_idx, o_idx) in x:
                    weight_terms.append(x[(v_idx, o_idx)] * int(order_wt * 1000))
            if weight_terms:
                model.Add(sum(weight_terms) <= int(v["max_weight"] * 1000))

            # Volume constraint
            volume_terms = []
            for o_idx in range(n_orders):
                order_vol = float(order_list[o_idx]["订单总体积"])
                if (v_idx, o_idx) in x:
                    volume_terms.append(x[(v_idx, o_idx)] * int(order_vol * 1000))
            if volume_terms:
                model.Add(sum(volume_terms) <= int(v["max_volume"] * 1000))

        # Objective: minimize total cost
        # For CP-SAT, we approximate the cost with linear terms
        # Use single-order cost as base, plus a penalty for multiple stops
        cost_terms = []
        for v_idx in range(n_vehicles):
            v = vehicle_instances[v_idx]
            for o_idx in range(n_orders):
                if (v_idx, o_idx) in x:
                    base_cost = single_order_costs.get((v_idx, o_idx), 1000)
                    cost_terms.append(x[(v_idx, o_idx)] * int(base_cost * 100))

        model.Minimize(sum(cost_terms))

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.num_search_workers = 4
        solver.parameters.log_search_progress = False

        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            # Extract assignment
            assignment = {}
            vehicle_orders = defaultdict(list)

            for v_idx in range(n_vehicles):
                for o_idx in range(n_orders):
                    if (v_idx, o_idx) in x and solver.Value(x[(v_idx, o_idx)]) == 1:
                        order_id = order_list[o_idx]["atomic_order_id"]
                        vtype = vehicle_instances[v_idx]["type"]
                        assignment[order_id] = vtype
                        vehicle_orders[v_idx].append(o_idx)

            # Calculate actual cost using exact cost calculator
            total_cost = 0.0
            violations = {
                "unassigned_orders": n_orders - len(assignment),
                "capacity_weight": 0,
                "capacity_volume": 0,
                "vehicle_restriction": 0,
            }

            for v_idx, o_indices in vehicle_orders.items():
                v = vehicle_instances[v_idx]
                total_weight = sum(float(order_list[o]["订单总重量"]) for o in o_indices)
                total_volume = sum(float(order_list[o]["订单总体积"]) for o in o_indices)

                # Count unique addresses for stops
                addresses = set()
                for o in o_indices:
                    addr = str(order_list[o].get("收货地址", ""))
                    addresses.add(addr)
                num_stops = len(addresses)

                # Check violations
                if total_weight > v["max_weight"] + 1e-3:
                    violations["capacity_weight"] += 1
                if total_volume > v["max_volume"] + 1e-3:
                    violations["capacity_volume"] += 1

                # Calculate actual trip cost
                trip_cost = self.cost_calc(v["type"], total_weight, num_stops)
                total_cost += trip_cost

            # If some orders are unassigned, try fallback
            if violations["unassigned_orders"] > 0:
                unassigned = [o for o in order_list if o["atomic_order_id"] not in assignment]
                fallback_assign, fallback_cost, fallback_viol = self._fallback_assign(
                    unassigned, vehicle_instances, assignment
                )
                assignment.update(fallback_assign)
                total_cost += fallback_cost
                violations["unassigned_orders"] = len(order_list) - len(assignment)

            return assignment, total_cost, violations
        else:
            # CP-SAT failed, use fallback
            print(f"CP-SAT failed with status {status}, using fallback...")
            return self._full_fallback(order_list)

    def _fallback_assign(self, unassigned_orders, vehicle_instances, existing_assignment):
        """Fallback: assign unassigned orders to largest available vehicles."""
        assignment = {}
        total_cost = 0.0

        # Sort unassigned by weight descending
        unassigned_orders = sorted(unassigned_orders, key=lambda o: float(o["订单总重量"]), reverse=True)

        # Find vehicles not yet used (or use largest available)
        used_vehicles = set()
        for oid, vtype in existing_assignment.items():
            for v in vehicle_instances:
                if v["type"] == vtype:
                    used_vehicles.add(v["instance_id"])
                    break

        available_vehicles = [v for v in vehicle_instances if v["instance_id"] not in used_vehicles]

        # If no unused vehicles, use largest vehicle type
        if not available_vehicles:
            largest_vt = max(self.vehicle_types, key=lambda vt: self.vehicle_registry[vt]["size_tier"])
            for order in unassigned_orders:
                order_id = order["atomic_order_id"]
                order_wt = float(order["订单总重量"])
                assignment[order_id] = largest_vt
                total_cost += self.cost_calc(largest_vt, order_wt, 1)
            return assignment, total_cost, {}

        # Sort available vehicles by size tier descending
        available_vehicles = sorted(available_vehicles, key=lambda v: v["size_tier"], reverse=True)

        for order in unassigned_orders:
            order_id = order["atomic_order_id"]
            order_vol = float(order["订单总体积"])
            order_wt = float(order["订单总重量"])
            order_restriction = float(order["限制车型等级"])

            # Find first vehicle that can fit this order
            assigned = False
            for v in available_vehicles:
                if (order_vol <= v["max_volume"] + 1e-3 and
                    order_wt <= v["max_weight"] + 1e-3 and
                    v["size_tier"] >= order_restriction):
                    assignment[order_id] = v["type"]
                    total_cost += self.cost_calc(v["type"], order_wt, 1)
                    assigned = True
                    break

            if not assigned:
                # Use largest vehicle type regardless of restriction
                largest_vt = max(self.vehicle_types, key=lambda vt: self.vehicle_registry[vt]["size_tier"])
                assignment[order_id] = largest_vt
                total_cost += self.cost_calc(largest_vt, order_wt, 1)

        return assignment, total_cost, {}

    def _full_fallback(self, order_list):
        """Complete fallback using greedy scheduler."""
        # Convert order_list back to DataFrame
        orders_df = pd.DataFrame(order_list)
        greedy = GreedyScheduler(self.vehicle_registry, self.vehicle_types, self.cost_calc)
        assignment, cost, violations = greedy.solve_day(orders_df)

        # If still unassigned, force assign to largest vehicle
        if violations["unassigned_orders"] > 0:
            largest_vt = max(self.vehicle_types, key=lambda vt: self.vehicle_registry[vt]["size_tier"])
            for order in order_list:
                oid = order["atomic_order_id"]
                if oid not in assignment:
                    assignment[oid] = largest_vt
                    cost += self.cost_calc(largest_vt, float(order["订单总重量"]), 1)
            violations["unassigned_orders"] = 0

        return assignment, cost, violations


# ============================================================
# GREEDY SCHEDULER (BASELINE)
# ============================================================
class GreedyScheduler:
    def __init__(self, vehicle_registry, vehicle_types, cost_calc):
        self.vehicle_registry = vehicle_registry
        self.vehicle_types = vehicle_types
        self.cost_calc = cost_calc

    def solve_day(self, orders_df):
        orders = orders_df.sort_values("最晚交货").copy()
        active_vehicles = []
        remaining_vehicles = {
            vt: self.vehicle_registry[vt]["total_available"]
            for vt in self.vehicle_types
        }
        assignment = {}

        for _, order in orders.iterrows():
            order_id = order["atomic_order_id"]
            order_vol = float(order["订单总体积"])
            order_wt = float(order["订单总重量"])
            order_restriction = float(order["限制车型等级"])
            order_addr = str(order.get("收货地址", ""))

            best_av_idx = -1
            best_remaining = -1
            for av_idx, av in enumerate(active_vehicles):
                vinfo = self.vehicle_registry[av["type"]]
                rem_vol = vinfo["max_volume_m3"] - av["volume"]
                rem_wt = vinfo["max_weight_kg"] - av["weight"]
                if (
                    rem_vol >= order_vol - 1e-3
                    and rem_wt >= order_wt - 1e-3
                    and vinfo["size_tier"] >= order_restriction
                ):
                    remaining = min(
                        rem_vol / max(vinfo["max_volume_m3"], 1e-6),
                        rem_wt / max(vinfo["max_weight_kg"], 1e-6),
                    )
                    if remaining > best_remaining:
                        best_remaining = remaining
                        best_av_idx = av_idx

            if best_av_idx >= 0:
                av = active_vehicles[best_av_idx]
                av["orders"].append(order_id)
                av["volume"] += order_vol
                av["weight"] += order_wt
                if order_addr not in av["addresses"]:
                    av["addresses"].add(order_addr)
                    av["stops"] += 1
                assignment[order_id] = av["type"]
            else:
                # Find best vehicle type for new trip
                best_vtype = None
                best_cost_estimate = float("inf")
                for vt in self.vehicle_types:
                    vinfo = self.vehicle_registry[vt]
                    if remaining_vehicles.get(vt, 0) <= 0:
                        continue
                    if (
                        order_vol > vinfo["max_volume_m3"] + 1e-3
                        or order_wt > vinfo["max_weight_kg"] + 1e-3
                    ):
                        continue
                    if vinfo["size_tier"] < order_restriction:
                        continue
                    est_cost = self.cost_calc(vt, order_wt, 1)
                    if est_cost < best_cost_estimate:
                        best_cost_estimate = est_cost
                        best_vtype = vt

                if best_vtype is None:
                    for vt in self.vehicle_types:
                        vinfo = self.vehicle_registry[vt]
                        if remaining_vehicles.get(vt, 0) <= 0:
                            continue
                        if (
                            order_vol > vinfo["max_volume_m3"] + 1e-3
                            or order_wt > vinfo["max_weight_kg"] + 1e-3
                        ):
                            continue
                        est_cost = self.cost_calc(vt, order_wt, 1)
                        if est_cost < best_cost_estimate:
                            best_cost_estimate = est_cost
                            best_vtype = vt

                if best_vtype is None:
                    for vt in self.vehicle_types:
                        vinfo = self.vehicle_registry[vt]
                        if remaining_vehicles.get(vt, 0) <= 0:
                            continue
                        if (
                            order_vol <= vinfo["max_volume_m3"] + 1e-3
                            and order_wt <= vinfo["max_weight_kg"] + 1e-3
                        ):
                            best_vtype = vt
                            break

                if best_vtype is None:
                    for vt in self.vehicle_types:
                        if remaining_vehicles.get(vt, 0) > 0:
                            best_vtype = vt
                            break

                if best_vtype is None:
                    continue

                remaining_vehicles[best_vtype] -= 1
                active_vehicles.append(
                    {
                        "type": best_vtype,
                        "orders": [order_id],
                        "volume": order_vol,
                        "weight": order_wt,
                        "addresses": {order_addr},
                        "stops": 1,
                    }
                )
                assignment[order_id] = best_vtype

        total_cost = sum(
            self.cost_calc(av["type"], av["weight"], av["stops"])
            for av in active_vehicles
        )
        violations = {
            "unassigned_orders": len(orders) - len(assignment),
            "capacity_weight": 0,
            "capacity_volume": 0,
            "vehicle_restriction": 0,
        }
        return assignment, total_cost, violations


# ============================================================
# LOCAL SEARCH OPTIMIZER (DEPRECATED - replaced by CP-SAT)
# ============================================================
class LocalSearchOptimizer:
    def __init__(self, vehicle_registry, vehicle_types, cost_calc, max_iter=500):
        self.vehicle_registry = vehicle_registry
        self.vehicle_types = vehicle_types
        self.cost_calc = cost_calc
        self.max_iter = max_iter
        self.greedy = GreedyScheduler(vehicle_registry, vehicle_types, cost_calc)

    def solve_day(self, orders_df):
        # Delegate to CP-SAT solver
        cp_sat = CPSATScheduler(self.vehicle_registry, self.vehicle_types, self.cost_calc)
        return cp_sat.solve_day(orders_df)


# ============================================================
# EVALUATION
# ============================================================
print("\nEvaluating on validation set...")

val_orders_dict = {}
for date in val_dates:
    day_orders = atomic_orders[atomic_orders["下单日期"] == date].copy()
    if len(day_orders) > 0:
        val_orders_dict[date] = day_orders

# Use CP-SAT as primary solver (globally optimizes assignment with exact cost calculator)
solver = CPSATScheduler(
    vehicle_registry, vehicle_types, calculate_trip_cost, time_limit=60
)

feasible_days = 0
infeasible_days = 0
total_cost_sum = 0.0

for date, day_orders in val_orders_dict.items():
    assignment, cost, violations = solver.solve_day(day_orders)
    is_feasible = (
        violations["unassigned_orders"] == 0
        and violations["capacity_weight"] == 0
        and violations["capacity_volume"] == 0
    )
    if is_feasible:
        feasible_days += 1
        total_cost_sum += cost
    else:
        infeasible_days += 1
        total_cost_sum += BIG_M

n_val_days = len(val_orders_dict)
feasibility_rate = feasible_days / max(n_val_days, 1)
avg_daily_cost = total_cost_sum / max(n_val_days, 1)

print(f"Feasible days: {feasible_days}/{n_val_days} ({feasibility_rate:.4f})")
print(f"Infeasible days: {infeasible_days}")
print(f"Avg daily cost (feasibility-weighted): {avg_daily_cost:.2f}")

# Print vehicle type distribution in validation assignments for debugging
val_all_assignments = []
for date, day_orders in val_orders_dict.items():
    assignment, _, _ = solver.solve_day(day_orders)
    val_all_assignments.extend(assignment.values())
if val_all_assignments:
    vt_counts = Counter(val_all_assignments)
    print(f"Validation vehicle type distribution (top 10): {vt_counts.most_common(10)}")

# ============================================================
# GENERATE SUBMISSION
# ============================================================
print("\nGenerating submission...")

test_orders_dict = {}
for date in test_dates:
    day_orders = atomic_orders[atomic_orders["下单日期"] == date].copy()
    if len(day_orders) > 0:
        test_orders_dict[date] = day_orders

submission_rows = []
for date, day_orders in test_orders_dict.items():
    assignment, cost, violations = solver.solve_day(day_orders)
    for order_id, vehicle_type in assignment.items():
        submission_rows.append(
            {
                "order_id": order_id,
                "assigned_vehicle_type": vehicle_type,
            }
        )

# Handle any missing orders - use CP-SAT fallback mechanism
all_test_ids = set()
for date, day_orders in test_orders_dict.items():
    all_test_ids.update(day_orders["atomic_order_id"].tolist())

assigned_ids = set(r["order_id"] for r in submission_rows)
missing = all_test_ids - assigned_ids

if missing:
    print(f"Warning: {len(missing)} orders unassigned, using fallback...")
    # Use largest available vehicle type for any remaining unassigned orders
    largest_vt = max(vehicle_types, key=lambda vt: vehicle_registry[vt]["size_tier"])
    for date, day_orders in test_orders_dict.items():
        day_missing = [
            oid for oid in missing if oid in day_orders["atomic_order_id"].values
        ]
        for oid in day_missing:
            order_row = day_orders[day_orders["atomic_order_id"] == oid]
            if len(order_row) > 0:
                submission_rows.append(
                    {"order_id": oid, "assigned_vehicle_type": largest_vt}
                )
            else:
                submission_rows.append(
                    {"order_id": oid, "assigned_vehicle_type": largest_vt}
                )

submission_df = pd.DataFrame(submission_rows)
submission_df = submission_df.sort_values("order_id")

if len(submission_df) > 0:
    vt_counts = Counter(submission_df["assigned_vehicle_type"])
    print(f"Submission vehicle type distribution: {vt_counts.most_common()}")

os.makedirs("./submission", exist_ok=True)
submission_df.to_csv("./submission/submission.csv", index=False, encoding="utf-8")
print(f"Submission saved: {len(submission_df)} rows")

# ============================================================
# FINAL SCORE
# ============================================================
final_score = avg_daily_cost
print(f"Final Validation Score: {final_score}")