"""solver/evaluator.py must agree with the exact simulator (gruber/simulator.py, which
matches the API on all saved parity responses).

Checked per truck on random valid routes from the saved snapshots: km, loaded km, cost,
CO2, finish time, driving minutes, break/rest minutes and fulfilled value. Also checks that
resuming from a saved mid-route state gives exactly the same result as a full simulation.
"""
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "solver"))

import evaluator as ev  # noqa: E402
from instance import load_instance  # noqa: E402

from gruber import loader, simulator  # noqa: E402
from tools import plangen  # noqa: E402

SCENARIOS = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"]


def _routes(sid, n_plans, seed):
    snaps = loader.list_snapshots(sid)
    if not snaps:
        pytest.skip(f"no snapshot for {sid}")
    sc = loader.load(sid)
    inst = load_instance(snaps[-1])
    oidx = {o.id: o.idx for o in inst.orders}
    tidx = {t.id: t.idx for t in inst.trucks}
    rng = random.Random(seed)
    for _ in range(n_plans):
        plan = plangen.random_valid_plan(sc, rng, frac=rng.choice([0.3, 0.6, 1.0]),
                                         consolidate=rng.random() < 0.7,
                                         n_trucks=rng.choice([None, 2, 4]))
        for tid, stops in plan.items():
            if stops:
                route = [(s["action"] == "pickup", oidx[s["order"]]) for s in stops]
                yield sc, inst, tidx[tid], tid, stops, route


@pytest.mark.parametrize("sid", SCENARIOS)
def test_evaluator_matches_simulator(sid):
    n = 0
    for sc, inst, k, tid, stops, route in _routes(sid, 60, seed=1):
        r = ev.simulate_truck(inst, k, route, early_exit=False)
        m = simulator.simulate(sc, {tid: stops})["metrics"]
        t = m["trucks"][0]
        got = (r.km, r.loaded_km, round(r.cost, 6), round(r.co2, 6), r.finish_min, r.drive_min,
               r.break_rest_min, round(r.value, 9))
        exp = (t["total_km"], t["loaded_km"], round(t["cost"], 6), round(t["co2"], 6),
               t["finish_min"], t["driving_min"], t["break_and_rest_min"],
               round(m["value_fulfilled"], 9))
        assert got == exp, f"{sid} {tid} route {route}"
        n += 1
    assert n > 50


@pytest.mark.parametrize("sid", SCENARIOS)
def test_resume_from_saved_state_is_exact(sid):
    rng = random.Random(7)
    n = 0
    for sc, inst, k, tid, stops, route in _routes(sid, 30, seed=2):
        if len(route) < 3:
            continue
        full = ev.simulate_truck(inst, k, route, early_exit=False, record=True)
        start = rng.randrange(1, len(route))
        # change the tail (drop one later stop pair's order), keep the first `start` stops
        tail_orders = [oi for _, oi in route[start:]]
        drop = rng.choice(tail_orders)
        if any(oi == drop for _, oi in route[:start]):
            continue
        new_route = [s for s in route if s[1] != drop]
        resumed = ev.simulate_truck(inst, k, new_route, early_exit=False, base=full, start=start,
                                    record=True)
        fresh = ev.simulate_truck(inst, k, new_route, early_exit=False, record=True)
        for f in ("km", "loaded_km", "cost", "co2", "value", "n_fulfilled", "finish_min",
                  "drive_min", "break_rest_min", "load_km", "max_load", "feasible"):
            assert getattr(resumed, f) == pytest.approx(getattr(fresh, f)), (sid, f)
        assert resumed.states == fresh.states
        n += 1
    assert n > 10
