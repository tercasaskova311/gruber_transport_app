"""Unit tests for the local simulator on small synthetic scenarios.

Validation semantics below were confirmed against the API's Validate endpoint.
"""
import json
from pathlib import Path

import pytest

from simulator import loader, simulator
from simulator.simulator import drive_minutes


def make_scenario(dist_rows, trucks, orders):
    ids = [f"C{i:03d}" for i in range(len(dist_rows))]
    dm = {a: {b: dist_rows[i][j] for j, b in enumerate(ids)} for i, a in enumerate(ids)}
    T = [dict(id=t[0], start_city=ids[t[1]], capacity_kg=t[2], type=t[3], cost_per_km=t[4],
              co2_per_km=t[5]) for t in trucks]
    O = []
    for o in orders:
        d = dict(id=o[0], pickup_city=ids[o[1]], delivery_city=ids[o[2]], weight_kg=o[3],
                 required_truck_type=o[4] if len(o) > 4 else None,
                 pickup_window=o[5] if len(o) > 5 else None,
                 delivery_window=o[6] if len(o) > 6 else None, value=o[7] if len(o) > 7 else 1)
        O.append(d)
    return loader.from_raw("synthetic", [], T, O, dm)


def P(o): return {"action": "pickup", "order": o}
def D(o): return {"action": "delivery", "order": o}


@pytest.fixture
def sc3():
    # 3 cities on a line: 0 --70km-- 1 --140km-- 2
    dist = [[0, 70, 210], [70, 0, 140], [210, 140, 0]]
    trucks = [("T01", 0, 10000, "standard", 1.0, 1.0), ("T02", 0, 5000, "hazmat", 2.0, 0.5)]
    orders = [("O1", 0, 1, 4000), ("O2", 1, 2, 7000), ("O3", 0, 2, 3000, "hazmat")]
    return make_scenario(dist, trucks, orders)


def rules(sim):
    return [(v["rule"], v["truck"], v["order"]) for v in sim["validation"]["violations"]]


def test_drive_minutes_ceil():
    assert drive_minutes(70) == 60
    assert drive_minutes(71) == 61      # 60.857 -> 61
    assert drive_minutes(0) == 0
    assert drive_minutes(1) == 1


def test_simple_route_metrics(sc3):
    plan = {"T01": [P("O1"), D("O1"), P("O2"), D("O2")]}
    sim = simulator.simulate(sc3, plan)
    m = sim["metrics"]
    assert sim["validation"]["is_valid"]
    assert m["total_km"] == 210 and m["loaded_km"] == 210 and m["empty_km"] == 0
    t = m["trucks"][0]
    # P@0 (0 km), D@1 (70km), P@1 (same city), D@2 (140km)
    arr = [e["arrival_min"] for e in t["schedule"]]
    assert arr == [0, 30 + 60, 120, 150 + 120]
    assert t["finish_min"] == 300
    assert t["route"] == ["C000", "C001", "C002"]
    assert t["max_load_kg"] == 7000
    assert m["orders_fulfilled"] == 2


def test_capacity_rejection_and_ignored_delivery(sc3):
    plan = {"T01": [P("O1"), P("O2"), D("O1"), D("O2"), P("O2"), D("O2")]}
    sim = simulator.simulate(sc3, plan)
    assert rules(sim) == [("capacity_exceeded", "T01", "O2"), ("duplicate_pickup", "T01", "O2")]
    assert sim["metrics"]["orders_fulfilled"] == 1


def test_type_mismatch_loaded_not_fulfilled(sc3):
    plan = {"T01": [P("O3"), D("O3")]}
    sim = simulator.simulate(sc3, plan)
    assert rules(sim) == [("truck_type_mismatch", "T01", "O3")]
    assert sim["metrics"]["orders_fulfilled"] == 0
    assert sim["metrics"]["loaded_km"] == 210


def test_ownership_and_order_of_violations(sc3):
    plan = {"T02": [D("O1")], "T01": [P("O1"), D("O1")], "T99": []}
    sim = simulator.simulate(sc3, plan)
    assert rules(sim) == [("delivery_before_pickup", "T02", "O1"),
                          ("order_assigned_multiple_times", "T01", "O1"),
                          ("order_assigned_multiple_times", "T01", "O1"),
                          ("unknown_truck", "T99", None)]


def test_action_case_insensitive(sc3):
    sim = simulator.simulate(sc3, {"T01": [{"action": "Pickup", "order": "O1"},
                                           {"action": "DELIVERY", "order": "O1"}]})
    assert sim["validation"]["is_valid"]


def test_score_formula(sc3):
    plan = {"T01": [P("O1"), D("O1")]}
    r = simulator.score(sc3, plan)
    direct = 70 + 140 + 210
    ref_km = direct * 1 / 3
    assert r["breakdown"]["fulfillment"] == pytest.approx(100 / 3)
    assert r["breakdown"]["cost_efficiency"] == pytest.approx(100 * min(1, ref_km * 1.0 / 70))
    assert r["breakdown"]["co2_efficiency"] == pytest.approx(100 * min(1, ref_km * 0.5 / 70))
    assert r["breakdown"]["loaded_ratio"] == pytest.approx(100)


def test_break_inserted_after_270_driving():
    # one leg of 700 km = 600 min driving: 270 drive, 45 break, 270 drive -> 540 = daily limit
    # then 11h rest, then 60 more
    dist = [[0, 700], [700, 0]]
    sc = make_scenario(dist, [("T01", 0, 10000, "standard", 1, 1)], [("O1", 0, 1, 100)])
    t = simulator.simulate(sc, {"T01": [P("O1"), D("O1")]})["metrics"]["trucks"][0]
    assert t["driving_min"] == 600
    assert t["break_and_rest_min"] == 45 + 660
    assert t["schedule"][1]["arrival_min"] == 30 + 600 + 45 + 660


# ------------------------------------------------------------ API parity fixtures
PARITY = Path(__file__).resolve().parent.parent / "data" / "parity" / "responses"


def _parity_cases():
    if not PARITY.exists():
        return []
    return sorted(PARITY.glob("*/*.json"))


@pytest.mark.parametrize("path", _parity_cases(), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_api_parity(path):
    from tools.parity import compare_one
    rec = json.loads(path.read_text())
    sc = loader.load(path.parent.name, rec["snapshot"])
    diffs = compare_one(sc, rec["plan"], path.stem.split(".")[-1], rec["response"])
    assert not diffs, "\n".join(diffs[:20])


def test_service_time_counts_toward_break():
    # 315 km = 270 min (exactly 4.5 h), then 30 min service, then more driving:
    # only 45 - 30 = 15 min of break is inserted (confirmed against the API).
    dist = [[0, 315, 385], [315, 0, 70], [385, 70, 0]]
    sc = make_scenario(dist, [("T01", 0, 10000, "standard", 1, 1)],
                       [("O1", 1, 2, 100)])
    t = simulator.simulate(sc, {"T01": [P("O1"), D("O1")]})["metrics"]["trucks"][0]
    assert t["schedule"][0]["arrival_min"] == 270
    assert t["break_and_rest_min"] == 15
    assert t["schedule"][1]["arrival_min"] == 270 + 30 + 15 + 60


def test_wait_of_45_resets_break_counter():
    # 270 min driving, then wait 15 + service 30 = 45 standing -> no break needed
    dist = [[0, 315, 385], [315, 0, 70], [385, 70, 0]]
    sc = make_scenario(dist, [("T01", 0, 10000, "standard", 1, 1)],
                       [("O1", 1, 2, 100, None, {"from": 285, "to": 400})])
    t = simulator.simulate(sc, {"T01": [P("O1"), D("O1")]})["metrics"]["trucks"][0]
    assert t["schedule"][0]["wait_min"] == 15
    assert t["break_and_rest_min"] == 0
    assert t["schedule"][1]["arrival_min"] == 285 + 30 + 60


def test_lateness_decay(sc3):
    # O1 delivered at city 1 at minute 90; window ends at 60 -> 30 min late -> 75 % value
    sc = make_scenario([[0, 70], [70, 0]], [("T01", 0, 10000, "standard", 1, 1)],
                       [("O1", 0, 1, 100, None, None, {"from": 0, "to": 60}, 1.5)])
    r = simulator.score(sc, {"T01": [P("O1"), D("O1")]})
    m = r["metrics"]
    assert m["trucks"][0]["schedule"][1]["late_min"] == 30
    assert m["value_fulfilled"] == pytest.approx(1.5 * 0.75)
    assert m["orders_late"] == 1 and m["penalized_late_min"] == 30
    sc2 = make_scenario([[0, 70], [70, 0]], [("T01", 0, 10000, "standard", 1, 1)],
                        [("O1", 0, 1, 100, None, None, {"from": 0, "to": 25}, 1.5)])
    m2 = simulator.simulate(sc2, {"T01": [P("O1"), D("O1")]})["metrics"]
    assert m2["orders_fulfilled"] == 0 and m2["orders_too_late"] == 1 and m2["orders_late"] == 1
