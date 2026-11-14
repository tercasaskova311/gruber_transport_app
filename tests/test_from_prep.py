"""The DB loader (instance.load_from_db, reads database's prep.*) must build the same
problem as the JSON loader (instance.load_instance). Compared by id, because positions may
differ. Then the solver must reach the same score on both.

Skipped when the DuckDB file is missing (run data_layer/run_all.sh). Fails if the DB and the
newest JSON snapshot hold different data, e.g. after a server restart: re-fetch both.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "solver"))

import evaluator as ev  # noqa: E402
from instance import load_from_db, load_instance  # noqa: E402
from settings import DB_PATH  # noqa: E402
from solver import construct  # noqa: E402

SCENARIOS = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"]

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason=f"no DuckDB at {DB_PATH}")
pytest.importorskip("duckdb")


def _pair(sid):
    from gruber.loader import list_snapshots  # newest first by timestamp, any naming style
    snaps = list_snapshots(sid)
    if not snaps:
        pytest.skip(f"no JSON snapshot for {sid}")
    return load_instance(snaps[-1]), load_from_db(sid)


def _orders(inst):
    c = inst.city_ids
    return {o.id: (c[o.p], c[o.d], o.weight, o.required_type, o.value, o.ptw, o.dtw) for o in inst.orders}


def _trucks(inst):
    c = inst.city_ids
    return {t.id: (c[t.start], t.capacity, t.type, t.cost_per_km, t.co2_per_km) for t in inst.trucks}


def _dist(inst):
    c = inst.city_ids
    return {(c[i], c[j]): km for i, row in enumerate(inst.D) for j, km in enumerate(row)}


def _compat(inst):
    return {o.id: {inst.trucks[k].id for k in inst.compatible[o.idx]} for o in inst.orders}


@pytest.mark.parametrize("sid", SCENARIOS)
def test_same_data(sid):
    js, db = _pair(sid)
    assert db.scenario_id == sid and db.snapshot_id
    assert _orders(db) == _orders(js)
    assert _trucks(db) == _trucks(js)
    assert _dist(db) == _dist(js)
    assert _compat(db) == _compat(js)
    for attr in ("value_total", "direct_km_total", "min_cost_per_km", "min_co2_per_km"):
        assert getattr(db, attr) == getattr(js, attr), attr


def _plan_score(inst, plan):
    """Score an id-based plan with the solver's evaluator."""
    oidx = {o.id: o.idx for o in inst.orders}
    tot = ev.Totals()
    for k, t in enumerate(inst.trucks):
        route = [(s["action"] == "pickup", oidx[s["order"]]) for s in plan.get(t.id, [])]
        tot.add(ev.simulate_truck(inst, k, route))
    return ev.score_value(inst, tot)


@pytest.mark.parametrize("sid", SCENARIOS)
def test_same_scores(sid):
    js, db = _pair(sid)
    sol_js, sol_db = construct(js, seed=0), construct(db, seed=0)
    # the same plan scores the same under both loaders
    plan = sol_js.to_plan(js)
    assert _plan_score(db, plan) == pytest.approx(_plan_score(js, plan), abs=1e-9)
    # and the deterministic construction ends at the same score
    assert sol_db.S == pytest.approx(sol_js.S, abs=1e-6)
