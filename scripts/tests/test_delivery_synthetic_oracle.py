"""Check independent acceptance-oracle witnesses and sensitivity at hard boundaries."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "verify-delivery-solver.py"
SPEC = importlib.util.spec_from_file_location("delivery_synthetic_oracle", SCRIPT)
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


def fixture(name):
    return deepcopy(next(value for value, _ in ORACLE.fixture_suite() if value["fixture_id"] == name))


def test_preparation_is_deterministic_and_separates_qualification(tmp_path):
    first = ORACLE.prepare(tmp_path / "one")
    second = ORACLE.prepare(tmp_path / "two")
    assert first["deterministic_suite_sha256"] == second["deterministic_suite_sha256"]
    assert first["algorithm_fixture_count"] == 27
    assert first["input_contract_fixture_count"] == 7
    assert first["candidate_executed"] is False
    for name in (tmp_path / "one" / "fixtures").glob("*.json"):
        assert name.read_bytes() == (tmp_path / "two" / "fixtures" / name.name).read_bytes()


def test_service_count_dominates_arbitrarily_large_exact_cost():
    value = fixture("service_count_before_cost")
    for rate in value["rates"]:
        if rate["carrier_id"] == "FULL":
            rate["rate_cents"] = 10**18
    answer = ORACLE.reference(value)
    assert answer["served_count"] == 2
    assert answer["cost_cents"] == 10**18 + 50


def test_capacity_mutation_changes_optimum_without_changing_denominator():
    value = fixture("insufficient_dated_capacity")
    before = ORACLE.reference(value)
    value["vehicle_slots"][0]["max_weight_kg"] = "1800"
    after = ORACLE.reference(value)
    assert (before["served_count"], before["cost_cents"]) == (2, 300)
    assert (after["served_count"], after["cost_cents"]) == (3, 600)
    assert before["coverage_denominator"] == after["coverage_denominator"] == 3


def test_second_day_slots_cannot_serve_first_day_orders():
    value = fixture("date_isolation_zero_slots_on_second_day")
    assert ORACLE.reference(value)["served_count"] == 1
    slot = value["vehicle_slots"][1]
    slot["date"] = "2035-04-18"
    slot["available_from"] = "2035-04-18T08:00:00"
    slot["available_until"] = "2035-04-18T23:59:59"
    answer = ORACLE.reference(value)
    assert answer["served_count"] == 2
    assert {route["date"] for route in answer["assignments"]} == {"2035-04-17", "2035-04-18"}


def test_cost_witness_retains_conversions_rounding_and_components():
    answer = ORACLE.reference(fixture("exact_units_minimum_fixed_and_explicit_surcharges"))
    costs = answer["assignments"][0]["cost_breakdown"]
    lines = costs["freight_lines"]
    assert [(line["physical_billing_quantity"], line["billed_quantity"], line["freight_cents"]) for line in lines] == [
        ("0.25", "0.5", 500), ("3", "3", 600), ("0.0005", "0.0005", 1)]
    assert costs["minimum_charge_topup_cents"] == 2899
    assert costs["route_fixed_cents"] == 500
    assert costs["route_surcharge_cents"] == 125
    assert costs["order_surcharge_sum_cents"] == 55
    assert costs["total_cents"] == 4680


def test_exact_time_and_reverse_loading_witness():
    value = fixture("inclusive_window_boundary_and_reverse_loading")
    answer = ORACLE.reference(value)
    timing = answer["assignments"][0]["schedule"]
    assert [stop["service_start"] for stop in timing["stops"]] == ["2035-04-17T08:05:00", "2035-04-17T08:11:00"]
    assert timing["loading_order"] == list(reversed(answer["assignments"][0]["order_ids"]))
    value["orders"][0]["delivery_service_seconds"] = 61
    assert ORACLE.reference(value)["served_count"] == 1


def test_blocked_and_complete_mathematical_infeasibility_are_distinct():
    blocked = ORACLE.reference(fixture("missing_capacity_date"))
    infeasible = ORACLE.reference(fixture("complete_but_time_infeasible"))
    assert blocked["status"] == "blocked_data_gap" and blocked["cost"] is None
    assert not blocked["proven_optimal"] and blocked["bound"] is None
    assert infeasible["status"] == "optimal" and infeasible["cost_cents"] == 0
    assert infeasible["served_count"] == 0 and infeasible["proven_optimal"]
    assert infeasible["data_gap_report"] == []


def test_transfer_temporal_flow_and_cost_are_explicit():
    answer = ORACLE.reference(fixture("authorized_transfer_on"))
    route = answer["assignments"][0]
    first, second = route["legs"]
    assert first["arrival"] == "2035-04-17T08:30:00"
    assert second["departure"] == "2035-04-17T08:40:00"
    assert first["weight_kg"] == second["weight_kg"] == "500"
    assert first["volume_m3"] == second["volume_m3"] == "3"
    assert route["cost_breakdown"] == {"transport_legs_cents": 2200, "handling_cents": 300, "total_cents": 2500}
    assert ORACLE.reference(fixture("authorized_transfer_off"))["cost_cents"] == 5000
    assert ORACLE.reference(fixture("transfer_hub_volume_capacity_binding"))["cost_cents"] == 5000
    assert ORACLE.reference(fixture("transfer_handling_prevents_early_departure"))["cost_cents"] == 5000


def test_oracle_rejects_routes_outside_proved_multi_trip_scope():
    value = fixture("minimum_cost_at_equal_coverage")
    value["orders"][1]["pickup_window"] = ["2035-04-17T10:00:00"] * 2
    with pytest.raises(ValueError, match="one common origin and pickup instant"):
        ORACLE.reference(value)


def test_provenance_and_input_order_do_not_change_optimum():
    value = fixture("historical_original_order_not_grouping")
    answer = ORACLE.reference(value)
    value["orders"].reverse()
    for index, order in enumerate(value["orders"]):
        order["original_order_id"] = "OTHER-PROVENANCE-" + str(index)
    changed = ORACLE.reference(value)
    assert (answer["served_count"], answer["cost_cents"]) == (changed["served_count"], changed["cost_cents"]) == (2, 200)
