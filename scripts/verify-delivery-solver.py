"""Prepare independent synthetic delivery fixtures and exhaustive reference optima.

This is an acceptance oracle, never a system candidate or a real dispatch plan.
The generated solver interface must be adapted separately before candidate scoring.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from itertools import combinations, permutations
import json
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "runs/industrial-examples-20260907/optimization-validation/delivery-synthetic-acceptance-v1"
DAY = "2035-04-17"
ISOLATED = ["FYP01", "MH101", "NH001", "SMG01", "YPF01"]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def moment(value):
    return datetime.fromisoformat(value)


def money(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def make_order(index, *, date=DAY, weight="100", volume="1", boxes="1", cost=100):
    return {
        "order_id": f"SYN-{date}-{index:02d}", "original_order_id": None,
        "customer_id": f"CUSTOMER-{index:02d}", "owner_id": "GENERAL",
        "goods_class": "general", "origin": "DEPOT", "destination": f"STOP-{index:02d}",
        "weight_kg": weight, "volume_m3": volume, "billing_boxes": boxes,
        "pickup_window": [date + "T08:00:00", date + "T08:00:00"],
        "delivery_window": [date + "T08:00:00", date + "T12:00:00"],
        "delivery_service_seconds": 60, "eligible_carriers": ["CARRIER-A"],
        "service": "delivery", "synthetic_default_freight_cents": cost,
    }


def make_slot(index, *, date=DAY, carrier="CARRIER-A", weight="1000", volume="10"):
    return {
        "slot_id": f"SYN-VEHICLE-{index:02d}", "date": date, "carrier_id": carrier,
        "vehicle_type": "SYN-VAN", "vehicle_variant": "explicit-standard",
        "max_weight_kg": weight, "max_volume_m3": volume,
        "available_from": date + "T08:00:00", "available_until": date + "T23:59:59",
        "start_location": "DEPOT", "starts_empty": True,
        "route_fixed_cents": 0, "route_minimum_freight_cents": 0, "route_surcharge_cents": 0,
    }


def base_fixture(name, orders, slots):
    fixture = {
        "schema": "independent-delivery-direct-v1", "fixture_id": name, "synthetic": True,
        "purpose": name, "orders": orders, "vehicle_slots": slots,
        "constraints": {"isolated_owners": ISOLATED, "owner_aliases": {},
                        "forbidden_goods_pairs": [["food", "pesticide"]],
                        "business_stop_limit": None},
        "semantics": {
            "objective": ["maximize_unweighted_served_order_count", "minimize_total_cost_cents"],
            "windows": "Inclusive service-start timestamps; service duration must fit vehicle availability.",
            "capacity": "All direct orders are picked up together at their common exact release instant.",
            "vehicle_reuse": "Positive travel and exact simultaneous pickup windows make a second pickup trip impossible; no trip or stop cap is imposed.",
            "travel": "Explicit synthetic integer-second directed matrix; no real-road or production ETA claim.",
            "route_cost": "max(sum(per_order_freight_cents), route_minimum_freight_cents) + route_fixed_cents + route_surcharge_cents + sum(order_surcharge_cents)",
            "rounding": "ROUND_HALF_UP to integer cents separately per order freight line.",
            "loading_sequence": "Reverse the feasible delivery sequence (last delivered, first loaded).",
            "original_order_id": "Provenance only; never compulsory grouping or an optimal label.",
        },
        "rates": [], "travel_seconds": {},
    }
    locations = ["DEPOT"] + [order["destination"] for order in orders]
    fixture["travel_seconds"] = {
        start: {end: 0 if start == end else 300 for end in locations} for start in locations
    }
    for order in orders:
        for carrier, kind in sorted({(slot["carrier_id"], slot["vehicle_type"]) for slot in slots}):
            if carrier not in order["eligible_carriers"]:
                continue
            fixture["rates"].append({
                "rate_id": f"RATE-{len(fixture['rates']):03d}", "carrier_id": carrier,
                "vehicle_type": kind, "customer_id": order["customer_id"],
                "origin": order["origin"], "destination": order["destination"],
                "service": order["service"], "active": True,
                "valid_from": "2035-01-01", "valid_until": "2035-12-31",
                "unit": "fixed", "rate_cents": order["synthetic_default_freight_cents"],
                "minimum_quantity": "0", "order_surcharge_cents": 0,
            })
    for order in orders:
        del order["synthetic_default_freight_cents"]
    return fixture


def matching_rates(fixture, order, slot):
    return [rate for rate in fixture["rates"]
            if rate["active"] is True
            and rate["carrier_id"] == slot["carrier_id"]
            and rate["vehicle_type"] == slot["vehicle_type"]
            and all(rate[key] == order[key] for key in ("customer_id", "origin", "destination", "service"))
            and rate["valid_from"] <= slot["date"] <= rate["valid_until"]]


def input_gaps(fixture):
    gaps = []
    if fixture["schema"] == "independent-delivery-transfer-v1":
        if fixture["transfer"]["authorized"] is None:
            gaps.append("transfer_authorization_missing")
        if fixture["transfer"]["authorized"] is True and fixture["transfer"].get("handling_cost_cents") is None:
            gaps.append("transfer_handling_cost_missing")
        return gaps
    for slot in fixture["vehicle_slots"]:
        if not slot.get("date"):
            gaps.append("capacity_date_missing:" + slot["slot_id"])
        if slot["vehicle_type"] == "4.2M" and not slot.get("vehicle_variant"):
            gaps.append("ambiguous_vehicle_variant:" + slot["slot_id"])
    for order in fixture["orders"]:
        for key in ("pickup_window", "delivery_window"):
            if any(moment(value).year < 2000 for value in order[key]):
                gaps.append("placeholder_time:" + order["order_id"])
            if moment(order[key][0]) > moment(order[key][1]):
                gaps.append("reversed_time_window:" + order["order_id"])
        for slot in fixture["vehicle_slots"]:
            if not slot.get("date") or slot["carrier_id"] not in order["eligible_carriers"]:
                continue
            if slot["date"] != moment(order["pickup_window"][0]).date().isoformat():
                continue
            rates = matching_rates(fixture, order, slot)
            if len(rates) != 1:
                gaps.append(f"rate_match_count_{len(rates)}:{order['order_id']}:{slot['slot_id']}")
            elif rates[0]["unit"] not in {"fixed", "tonne", "box"}:
                gaps.append("unknown_billing_unit:" + rates[0]["rate_id"])
    return sorted(set(gaps))


def freight(order, rate):
    if rate["unit"] == "fixed":
        quantity = Decimal(1)
    elif rate["unit"] == "tonne":
        quantity = Decimal(order["weight_kg"]) / Decimal(1000)
    else:
        quantity = Decimal(order["billing_boxes"])
    billed_quantity = max(quantity, Decimal(rate["minimum_quantity"]))
    return {
        "order_id": order["order_id"], "rate_id": rate["rate_id"], "unit": rate["unit"],
        "physical_billing_quantity": str(quantity), "billed_quantity": str(billed_quantity),
        "freight_cents": money(billed_quantity * Decimal(rate["rate_cents"])),
        "order_surcharge_cents": rate["order_surcharge_cents"],
    }


def route_cost(fixture, subset, slot):
    lines = [freight(order, matching_rates(fixture, order, slot)[0]) for order in subset]
    raw = sum(line["freight_cents"] for line in lines)
    minimum_topup = max(0, slot["route_minimum_freight_cents"] - raw)
    total = raw + minimum_topup + slot["route_fixed_cents"] + slot["route_surcharge_cents"]
    total += sum(line["order_surcharge_cents"] for line in lines)
    return {
        "freight_lines": lines, "freight_sum_cents": raw, "minimum_charge_topup_cents": minimum_topup,
        "route_fixed_cents": slot["route_fixed_cents"], "route_surcharge_cents": slot["route_surcharge_cents"],
        "order_surcharge_sum_cents": sum(line["order_surcharge_cents"] for line in lines), "total_cents": total,
    }


def compatible(fixture, subset, slot):
    aliases = fixture["constraints"]["owner_aliases"]
    owners = {aliases.get(order["owner_id"], order["owner_id"]) for order in subset}
    if len(owners) > 1 and owners.intersection(fixture["constraints"]["isolated_owners"]):
        return False
    goods = {order["goods_class"] for order in subset}
    if any(set(pair).issubset(goods) for pair in fixture["constraints"]["forbidden_goods_pairs"]):
        return False
    if sum(Decimal(order["weight_kg"]) for order in subset) > Decimal(slot["max_weight_kg"]):
        return False
    if sum(Decimal(order["volume_m3"]) for order in subset) > Decimal(slot["max_volume_m3"]):
        return False
    return all(slot["carrier_id"] in order["eligible_carriers"]
               and order["origin"] == slot["start_location"]
               and slot["date"] == moment(order["pickup_window"][0]).date().isoformat()
               for order in subset)


def schedule(fixture, sequence, slot):
    start = max([moment(slot["available_from"])] + [moment(order["pickup_window"][0]) for order in sequence])
    if any(start > moment(order["pickup_window"][1]) for order in sequence):
        return None
    current, location, stops = start, slot["start_location"], []
    for order in sequence:
        arrival = current + timedelta(seconds=fixture["travel_seconds"][location][order["destination"]])
        service_start = max(arrival, moment(order["delivery_window"][0]))
        if service_start > moment(order["delivery_window"][1]):
            return None
        current = service_start + timedelta(seconds=order["delivery_service_seconds"])
        if current > moment(slot["available_until"]):
            return None
        stops.append({"order_id": order["order_id"], "arrival": arrival.isoformat(),
                      "service_start": service_start.isoformat(), "service_end": current.isoformat()})
        location = order["destination"]
    return {"pickup_time": start.isoformat(), "stops": stops,
            "loading_order": [order["order_id"] for order in reversed(sequence)],
            "finish_time": current.isoformat()}


def direct_reference(fixture):
    orders = fixture["orders"]
    if len(orders) > 8:
        raise ValueError("The independent exhaustive oracle is intentionally limited to 8 orders")
    for order in orders:
        if order["pickup_window"][0] != order["pickup_window"][1]:
            raise ValueError("Direct fixture requires exact pickup instants to prove no repeated pickup trip")
    release_by_date = {}
    for order in orders:
        release = order["pickup_window"][0]
        date = moment(release).date().isoformat()
        release_by_date.setdefault(date, set()).add((order["origin"], release))
    if any(len(values) != 1 for values in release_by_date.values()):
        raise ValueError("Direct oracle requires one common origin and pickup instant per date")
    if not all(slot["starts_empty"] for slot in fixture["vehicle_slots"]):
        raise ValueError("Direct fixture schema requires explicitly empty starting vehicles")
    if any(value <= 0 for start, destinations in fixture["travel_seconds"].items()
           for end, value in destinations.items() if start != end):
        raise ValueError("Distinct synthetic locations need strictly positive travel time")
    explored = {"subsets": 0, "route_permutations": 0, "assignment_transitions": 0}
    route_sets, feasible_singletons = [], set()
    for slot in fixture["vehicle_slots"]:
        routes = [(0, {"cost_cents": 0, "slot_id": slot["slot_id"], "order_ids": []})]
        for size in range(1, len(orders) + 1):
            for indices in combinations(range(len(orders)), size):
                explored["subsets"] += 1
                subset = [orders[index] for index in indices]
                if not compatible(fixture, subset, slot):
                    continue
                for sequence in permutations(subset):
                    explored["route_permutations"] += 1
                    timing = schedule(fixture, sequence, slot)
                    if timing is None:
                        continue
                    cost = route_cost(fixture, subset, slot)
                    route = {"slot_id": slot["slot_id"], "date": slot["date"],
                             "order_ids": [order["order_id"] for order in sequence],
                             "cost_cents": cost["total_cents"], "cost_breakdown": cost, "schedule": timing,
                             "weight_kg": str(sum(Decimal(order["weight_kg"]) for order in subset)),
                             "volume_m3": str(sum(Decimal(order["volume_m3"]) for order in subset))}
                    routes.append((sum(1 << index for index in indices), route))
                    if size == 1:
                        feasible_singletons.add(indices[0])
                    # Costs are explicitly independent of stop sequence in this fixture schema.
                    break
        route_sets.append(routes)
    states = {0: (0, [])}
    for routes in route_sets:
        next_states = {}
        for served_mask, (cost, chosen) in states.items():
            for route_mask, route in routes:
                explored["assignment_transitions"] += 1
                if route_mask & served_mask:
                    continue
                merged, total = served_mask | route_mask, cost + route["cost_cents"]
                if merged not in next_states or total < next_states[merged][0]:
                    next_states[merged] = (total, chosen + ([route] if route_mask else []))
        states = next_states
    mask, (cost, assignments) = min(states.items(), key=lambda item: (-item[0].bit_count(), item[1][0], item[0]))
    unserved = [{"order_id": order["order_id"],
                "reason": "no_individually_feasible_route" if index not in feasible_singletons
                else "not_selected_under_finite_capacity_and_joint_constraints"}
               for index, order in enumerate(orders) if not mask & (1 << index)]
    return {
        "status": "optimal", "coverage_denominator": len(orders), "served_count": mask.bit_count(),
        "unserved_count": len(unserved), "unserved_orders": unserved,
        "cost_cents": cost, "assignments": assignments, "constraint_violations": [],
        "bound": {"max_served_count": mask.bit_count(), "min_cost_at_max_coverage_cents": cost},
        "absolute_cost_gap_cents": 0, "proven_optimal": True,
        "method": "All vehicle/subset routes with permutation feasibility, followed by exact disjoint-subset dynamic programming.",
        "enumeration": explored,
    }


def transfer_fixture(name, authorized):
    order = make_order(90, weight="500", volume="3")
    del order["synthetic_default_freight_cents"]
    order["delivery_window"] = [DAY + "T08:00:00", DAY + "T10:00:00"]
    order["destination"] = "DESTINATION"
    fixture = {
        "schema": "independent-delivery-transfer-v1", "fixture_id": name, "synthetic": True,
        "purpose": "Single indivisible order with independently authorized finite one-hub transport paths.",
        "orders": [order],
        "transfer": {"authorized": authorized, "allowed_hub": "HUB", "handling_seconds": 600,
                     "handling_cost_cents": 300, "hub_capacity_weight_kg": "500",
                     "hub_capacity_volume_m3": "3", "incoming_empty_required": True},
        "vehicle_slots": [
            {"slot_id": "DIRECT", "date": DAY, "available_from": DAY + "T08:00:00",
             "available_until": DAY + "T12:00:00", "max_weight_kg": "1000", "max_volume_m3": "10", "starts_empty": True},
            {"slot_id": "INBOUND", "date": DAY, "available_from": DAY + "T08:00:00",
             "available_until": DAY + "T08:30:00", "max_weight_kg": "500", "max_volume_m3": "3", "starts_empty": True},
            {"slot_id": "OUTBOUND", "date": DAY, "available_from": DAY + "T08:40:00",
             "available_until": DAY + "T10:00:00", "max_weight_kg": "500", "max_volume_m3": "3", "starts_empty": True},
        ],
        "transport_legs": [
            {"slot_id": "DIRECT", "origin": "DEPOT", "destination": "DESTINATION", "travel_seconds": 3600, "cost_cents": 5000},
            {"slot_id": "INBOUND", "origin": "DEPOT", "destination": "HUB", "travel_seconds": 1800, "cost_cents": 1000},
            {"slot_id": "OUTBOUND", "origin": "HUB", "destination": "DESTINATION", "travel_seconds": 1200, "cost_cents": 1200},
        ],
        "semantics": {"scope": "Exactly one indivisible order and explicit service legs; no arbitrary transfers or general multi-order routing claim.",
                      "objective": ["maximize_unweighted_served_order_count", "minimize_total_cost_cents"],
                      "hub_inventory": "Inbound arrival precedes handling, which precedes outbound pickup; weight and volume conserved.",
                      "transport_leg_cost": "Explicit synthetic per-leg complete charge in cents; handling is additional.",
                      "windows": "Inclusive pickup/service-start bounds; unloading service duration also fits availability."},
    }
    return fixture


def transfer_reference(fixture):
    if len(fixture["orders"]) != 1:
        raise ValueError("Transfer oracle only supports its declared single-order scope")
    order = fixture["orders"][0]
    slots = {slot["slot_id"]: slot for slot in fixture["vehicle_slots"]}
    legs = fixture["transport_legs"]
    paths = [[leg] for leg in legs if leg["origin"] == order["origin"] and leg["destination"] == order["destination"]]
    transfer = fixture["transfer"]
    if transfer["authorized"] is True:
        paths.extend([first, second] for first in legs for second in legs
                     if first["origin"] == order["origin"] and first["destination"] == transfer["allowed_hub"]
                     and second["origin"] == transfer["allowed_hub"] and second["destination"] == order["destination"]
                     and first["slot_id"] != second["slot_id"])
    feasible = []
    for path in paths:
        ready = moment(order["pickup_window"][0])
        timing, valid = [], True
        if len(path) > 1 and (Decimal(order["weight_kg"]) > Decimal(transfer["hub_capacity_weight_kg"])
                              or Decimal(order["volume_m3"]) > Decimal(transfer["hub_capacity_volume_m3"])):
            continue
        for index, leg in enumerate(path):
            slot = slots[leg["slot_id"]]
            departure = max(ready, moment(slot["available_from"]))
            arrival = departure + timedelta(seconds=leg["travel_seconds"])
            final_leg = index == len(path) - 1
            service_start = max(arrival, moment(order["delivery_window"][0])) if final_leg else arrival
            finish = service_start + timedelta(seconds=order["delivery_service_seconds"] if final_leg else 0)
            if (departure.date().isoformat() != slot["date"] or not slot["starts_empty"]
                    or Decimal(order["weight_kg"]) > Decimal(slot["max_weight_kg"])
                    or Decimal(order["volume_m3"]) > Decimal(slot["max_volume_m3"])
                    or finish > moment(slot["available_until"])
                    or (index == 0 and departure > moment(order["pickup_window"][1]))
                    or (final_leg and service_start > moment(order["delivery_window"][1]))):
                valid = False
                break
            timing.append({**leg, "departure": departure.isoformat(), "arrival": arrival.isoformat(),
                           "service_start": service_start.isoformat(), "finish": finish.isoformat(),
                           "order_id": order["order_id"], "weight_kg": order["weight_kg"], "volume_m3": order["volume_m3"]})
            ready = finish + timedelta(seconds=transfer["handling_seconds"] if not final_leg else 0)
        if valid:
            handling = transfer["handling_cost_cents"] if len(path) > 1 else 0
            cost = sum(leg["cost_cents"] for leg in path) + handling
            feasible.append({"order_id": order["order_id"], "legs": timing, "cost_cents": cost,
                             "cost_breakdown": {"transport_legs_cents": sum(leg["cost_cents"] for leg in path),
                                                "handling_cents": handling, "total_cents": cost},
                             "conserved_weight_kg": order["weight_kg"], "conserved_volume_m3": order["volume_m3"]})
    best = min(feasible, key=lambda item: item["cost_cents"]) if feasible else None
    count, cost = int(best is not None), best["cost_cents"] if best else 0
    return {"status": "optimal", "coverage_denominator": 1, "served_count": count, "unserved_count": 1 - count,
            "unserved_orders": [] if best else [{"order_id": order["order_id"], "reason": "no_feasible_authorized_transport_path"}],
            "assignments": [best] if best else [], "cost_cents": cost, "constraint_violations": [],
            "bound": {"max_served_count": count, "min_cost_at_max_coverage_cents": cost},
            "absolute_cost_gap_cents": 0, "proven_optimal": True,
            "method": "Enumerate every explicitly authorized direct or one-hub path for the single indivisible order.",
            "enumeration": {"paths_checked": len(paths), "feasible_paths": len(feasible)}}


def reference(fixture):
    gaps = input_gaps(fixture)
    if gaps:
        return {"status": "blocked_data_gap", "assignments": [], "cost": None, "cost_cents": None,
                "coverage_denominator": len(fixture["orders"]), "served_count": 0,
                "unserved_count": len(fixture["orders"]),
                "unserved_orders": [{"order_id": order["order_id"], "reason": "required_input_data_gap"} for order in fixture["orders"]],
                "constraint_audit": {"passed": False, "data_gaps": gaps}, "data_gap_report": gaps,
                "constraint_violations": [], "proven_optimal": False, "bound": None,
                "absolute_cost_gap_cents": None, "method": "Input-contract qualification only; excluded from algorithm optimality scoring."}
    result = transfer_reference(fixture) if fixture["schema"] == "independent-delivery-transfer-v1" else direct_reference(fixture)
    result["cost"] = {"currency": "CNY", "amount_cents": result["cost_cents"]}
    result["constraint_audit"] = {"passed": True, "data_gaps": []}
    result["data_gap_report"] = []
    return result


def fixture_suite():
    suite = []

    def add(fixture, count=None, cost=None, *, gap=None):
        fixture["verification_group"] = "input_contract" if gap else "algorithm_optimality"
        expected = {"status": "blocked_data_gap", "required_gap_prefix": gap} if gap else {"status": "optimal", "served_count": count, "cost_cents": cost}
        suite.append((fixture, expected))

    orders = [make_order(1, weight="600", cost=50), make_order(2, weight="600", cost=50)]
    for order in orders:
        order["eligible_carriers"] = ["CHEAP", "FULL"]
    fixture = base_fixture("service_count_before_cost", orders, [make_slot(1, carrier="CHEAP", weight="600"), make_slot(2, carrier="FULL", weight="1200")])
    for rate in fixture["rates"]:
        rate["rate_cents"] = 5000 if rate["carrier_id"] == "FULL" else 50
    add(fixture, 2, 5050)

    orders = [make_order(1), make_order(2)]
    for order in orders:
        order["eligible_carriers"] = ["EXPENSIVE", "CHEAP"]
    fixture = base_fixture("minimum_cost_at_equal_coverage", orders, [make_slot(1, carrier="EXPENSIVE"), make_slot(2, carrier="CHEAP")])
    for rate in fixture["rates"]:
        rate["rate_cents"] = 900 if rate["carrier_id"] == "EXPENSIVE" else 100
    add(fixture, 2, 200)

    add(base_fixture("insufficient_dated_capacity", [make_order(i, weight="600", cost=i * 100) for i in range(1, 4)],
                     [make_slot(1, weight="1200")]), 2, 300)
    add(base_fixture("weight_binding", [make_order(i, weight="600", volume="1", cost=i * 100) for i in (1, 2)],
                     [make_slot(1, weight="1000", volume="10")]), 1, 100)
    add(base_fixture("volume_binding", [make_order(i, weight="100", volume="6", cost=i * 100) for i in (1, 2)],
                     [make_slot(1, weight="1000", volume="10")]), 1, 100)
    add(base_fixture("exact_dual_capacity_boundary", [make_order(i, weight="500", volume="5") for i in (1, 2)],
                     [make_slot(1, weight="1000", volume="10")]), 2, 200)
    for variant, weight, volume, expected in [("electric", "4000", "16", 1), ("diesel", "5000", "18", 2)]:
        slot = make_slot(1, weight=weight, volume=volume)
        slot.update(vehicle_type="4.2M", vehicle_variant=variant)
        add(base_fixture("explicit_4_2m_" + variant + "_capacity", [make_order(i, weight="2200", volume="8.5") for i in (1, 2)],
                         [slot]), expected, expected * 100)
    add(base_fixture("date_isolation_zero_slots_on_second_day", [make_order(1), make_order(2, date="2035-04-18")],
                     [make_slot(1), make_slot(2)]), 1, 100)

    orders = [make_order(i, weight="1", volume="1") for i in range(1, 8)]
    for order, owner in zip(orders, ISOLATED + ["GENERAL", "GENERAL"]):
        order["owner_id"] = owner
    add(base_fixture("all_five_isolated_owners", orders, [make_slot(1, volume="10")]), 2, 200)
    orders = [make_order(1), make_order(2)]
    orders[0]["owner_id"] = "MHI01"
    fixture = base_fixture("explicit_synthetic_owner_alias", orders, [make_slot(1)])
    fixture["constraints"]["owner_aliases"] = {"MHI01": "MH101"}
    add(fixture, 1, 100)
    orders = [make_order(1, cost=100), make_order(2, cost=200)]
    orders[0]["goods_class"], orders[1]["goods_class"] = "food", "pesticide"
    add(base_fixture("food_pesticide_incompatibility", orders, [make_slot(1)]), 1, 100)
    orders = [make_order(1, weight="600"), make_order(2, weight="600")]
    for order in orders:
        order["original_order_id"] = "SYN-HISTORICAL-PROVENANCE-ONLY"
    add(base_fixture("historical_original_order_not_grouping", orders, [make_slot(1, weight="600"), make_slot(2, weight="600")]), 2, 200)
    add(base_fixture("eight_stops_without_invented_cap", [make_order(i, weight="10", volume="0.1") for i in range(1, 9)], [make_slot(1)]), 8, 800)

    orders = [make_order(1), make_order(2, cost=200)]
    for order in orders:
        order["delivery_window"] = [DAY + "T08:05:00", DAY + "T08:05:00"]
    add(base_fixture("same_day_incompatible_exact_windows", orders, [make_slot(1)]), 1, 100)
    orders = [make_order(1), make_order(2)]
    orders[0]["delivery_window"] = [DAY + "T08:05:00", DAY + "T08:05:00"]
    orders[1]["delivery_window"] = [DAY + "T08:11:00", DAY + "T08:11:00"]
    add(base_fixture("inclusive_window_boundary_and_reverse_loading", orders, [make_slot(1)]), 2, 200)
    order = make_order(1)
    order["pickup_window"] = [DAY + "T23:50:00"] * 2
    order["delivery_window"] = ["2035-04-18T00:05:00"] * 2
    slot = make_slot(1)
    slot.update(available_from=DAY + "T23:50:00", available_until="2035-04-18T00:06:00")
    fixture = base_fixture("cross_day_exact_delivery_window", [order], [slot])
    fixture["travel_seconds"]["DEPOT"]["STOP-01"] = 900
    add(fixture, 1, 100)
    fixture = deepcopy(fixture)
    fixture["fixture_id"] = "complete_but_time_infeasible"
    fixture["travel_seconds"]["DEPOT"]["STOP-01"] = 901
    add(fixture, 0, 0)

    orders = [make_order(1, weight="250"), make_order(2, weight="750", boxes="3"), make_order(3, weight="0.5")]
    slot = make_slot(1, weight="1200")
    slot.update(route_fixed_cents=500, route_minimum_freight_cents=4000, route_surcharge_cents=125)
    fixture = base_fixture("exact_units_minimum_fixed_and_explicit_surcharges", orders, [slot])
    fixture["rates"][0].update(unit="tonne", rate_cents=1000, minimum_quantity="0.5", order_surcharge_cents=25)
    fixture["rates"][1].update(unit="box", rate_cents=200, minimum_quantity="0", order_surcharge_cents=30)
    fixture["rates"][2].update(unit="tonne", rate_cents=1000, minimum_quantity="0")
    add(fixture, 3, 4680)
    for grams, expected in [("499", 500), ("500", 500), ("501", 501)]:
        fixture = base_fixture("tonne_minimum_boundary_" + grams + "kg", [make_order(1, weight=grams)], [make_slot(1)])
        fixture["rates"][0].update(unit="tonne", rate_cents=1000, minimum_quantity="0.5")
        add(fixture, 1, expected)
    fixture = base_fixture("contract_exact_dimensions_ignore_inapplicable_cheap_rates", [make_order(1)], [make_slot(1)])
    for changes in [{"active": False}, {"valid_until": "2034-12-31"}, {"carrier_id": "WRONG"},
                    {"customer_id": "WRONG"}, {"vehicle_type": "WRONG"}, {"origin": "WRONG"},
                    {"destination": "WRONG"}, {"service": "transfer"}]:
        invalid = {**deepcopy(fixture["rates"][0]), **changes, "rate_cents": 0, "rate_id": f"INAPPLICABLE-{len(fixture['rates'])}"}
        fixture["rates"].append(invalid)
    add(fixture, 1, 100)

    for enabled, expected in [(False, 5000), (True, 2500)]:
        add(transfer_fixture("authorized_transfer_" + ("on" if enabled else "off"), enabled), 1, expected)
    fixture = transfer_fixture("transfer_handling_prevents_early_departure", True)
    fixture["vehicle_slots"][2]["available_until"] = DAY + "T08:59:59"
    add(fixture, 1, 5000)
    fixture = transfer_fixture("transfer_hub_volume_capacity_binding", True)
    fixture["transfer"]["hub_capacity_volume_m3"] = "2.99"
    add(fixture, 1, 5000)
    add(transfer_fixture("transfer_missing_authorization", None), gap="transfer_authorization_missing")
    fixture = transfer_fixture("transfer_missing_handling_cost", True)
    fixture["transfer"]["handling_cost_cents"] = None
    add(fixture, gap="transfer_handling_cost_missing")
    fixture = base_fixture("missing_capacity_date", [make_order(1)], [make_slot(1)])
    fixture["vehicle_slots"][0]["date"] = None
    add(fixture, gap="capacity_date_missing")
    fixture = base_fixture("ambiguous_electric_diesel_variant", [make_order(1)], [make_slot(1)])
    fixture["vehicle_slots"][0].update(vehicle_type="4.2M", vehicle_variant=None)
    fixture["rates"][0]["vehicle_type"] = "4.2M"
    add(fixture, gap="ambiguous_vehicle_variant")
    fixture = base_fixture("placeholder_1899_time", [make_order(1)], [make_slot(1)])
    fixture["orders"][0]["delivery_window"] = ["1899-12-30T08:00:00"] * 2
    add(fixture, gap="placeholder_time")
    fixture = base_fixture("unknown_rate_unit", [make_order(1)], [make_slot(1)])
    fixture["rates"][0]["unit"] = "ambiguous_box_conversion"
    add(fixture, gap="unknown_billing_unit")
    fixture = base_fixture("ambiguous_active_matching_contracts", [make_order(1)], [make_slot(1)])
    fixture["rates"].append({**deepcopy(fixture["rates"][0]), "rate_id": "OTHER-ACTIVE", "rate_cents": 1})
    add(fixture, gap="rate_match_count_2")
    return suite


def prepare(destination):
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for fixture, expected in fixture_suite():
        start = time.perf_counter()
        answer = reference(fixture)
        elapsed = time.perf_counter() - start
        if expected["status"] == "blocked_data_gap":
            passed = (answer["status"] == expected["status"] and answer["cost"] is None
                      and answer["assignments"] == [] and any(gap.startswith(expected["required_gap_prefix"]) for gap in answer["data_gap_report"]))
        else:
            passed = all(answer[key] == value for key, value in expected.items())
        if not passed:
            raise AssertionError(f"Independent hand-derived objective check failed for {fixture['fixture_id']}: {answer} != {expected}")
        fixture_hash = digest(fixture)
        record = {"fixture_id": fixture["fixture_id"], "fixture_sha256": fixture_hash,
                  "reference_sha256": digest(answer), "synthetic": True, "candidate_executed": False,
                  "verification_group": fixture["verification_group"], "independent_reference": answer,
                  "hand_derived_expected": expected, "hand_derived_check_passed": passed}
        save(destination / "fixtures" / (fixture["fixture_id"] + ".json"), fixture)
        save(destination / "references" / (fixture["fixture_id"] + ".json"), record)
        rows.append({"fixture_id": fixture["fixture_id"], "fixture_sha256": fixture_hash,
                     "reference_sha256": digest(answer), "verification_group": fixture["verification_group"],
                     "orders": len(fixture["orders"]), "vehicle_slots": len(fixture["vehicle_slots"]),
                     "status": answer["status"], "served_count": answer["served_count"], "cost_cents": answer["cost_cents"],
                     "reference_runtime_seconds": elapsed, "hand_derived_check_passed": passed})
    result = {
        "synthetic": True, "prepared": True, "candidate_executed": False,
        "fixture_count": len(rows), "algorithm_fixture_count": sum(row["verification_group"] == "algorithm_optimality" for row in rows),
        "input_contract_fixture_count": sum(row["verification_group"] == "input_contract" for row in rows),
        "deterministic_suite_sha256": digest([{key: value for key, value in row.items() if key != "reference_runtime_seconds"} for row in rows]),
        "seed": None, "randomness": "None; deterministic enumeration and exact monetary arithmetic.",
        "candidate_adapter_status": "pending_actual_generated_solver_interface",
        "limitations": [
            "Synthetic software and algorithm validation only; no real dispatch, dates, savings, or SLA claims.",
            "Direct fixtures use a common exact pickup instant per date and positive travel, proving no second pickup trip can serve another order.",
            "Direct route costs are explicitly independent of stop order, so only the first feasible permutation is needed per subset.",
            "Transfer fixtures exhaustively cover one indivisible order and explicit direct/one-hub service legs, not general multi-order transshipment.",
            "Contract dimensions and charge meanings are explicit synthetic inputs; unresolved real aliases and source contract semantics remain unresolved.",
            "This reference program is an independent acceptance oracle, not a generated system candidate and not evidence that the system solver passed.",
        ],
        "candidate_acceptance": {
            "all_complete_fixtures": "Must return feasible assignments achieving the exact maximal served count, then exact minimal cost; blocked_data_gap fails.",
            "all_input_contract_fixtures": "Must expose the required gap with empty assignments and null cost; excluded from algorithm quality scores.",
            "must_record": ["fixture_hash", "frozen_model_hash", "candidate_config_and_seed", "candidate_runtime_seconds", "coverage_denominator",
                            "unserved_orders_and_reasons", "independently_recomputed_violations", "independently_recomputed_cost_breakdown",
                            "reference_max_coverage", "reference_min_cost_at_max_coverage", "coverage_gap", "absolute_cost_gap_cents"],
            "must_run": "Load the same exported frozen solver and config in a new process from a moved directory, with original data unavailable and no LLM calls.",
        },
        "fixtures": rows,
    }
    save(destination / "manifest.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Write synthetic inputs and independently enumerated references; do not run a candidate.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not args.prepare:
        parser.error("Only --prepare is available until the actual generated solver interface has been independently inspected.")
    result = prepare(args.output_dir.resolve())
    print(json.dumps({key: result[key] for key in ("prepared", "synthetic", "fixture_count", "algorithm_fixture_count", "input_contract_fixture_count", "deterministic_suite_sha256", "candidate_executed")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
