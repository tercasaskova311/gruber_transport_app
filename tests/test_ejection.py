"""solver/ejection.py: an ejection sweep must never lower the score, must keep the plan
valid, and its score must equal the exact simulator's."""
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "solver"))

import ejection  # noqa: E402
from instance import load_instance  # noqa: E402
from solver import check_plan, construct  # noqa: E402

from simulator import loader, simulator  # noqa: E402

DIRS = sorted((ROOT / "data" / "fake").glob("fake_*")) + \
    [s for sid in ("scenario_big", "scenario_competitive") for s in loader.list_snapshots(sid)[-1:]]


@pytest.mark.parametrize("folder", DIRS, ids=lambda p: p.parent.name + "/" + p.name)
def test_sweep_improves_and_stays_valid(folder):
    import json
    inst = load_instance(folder)
    start = construct(inst, seed=1, regret=1)
    sol, moves = ejection.eject_sweep(inst, start.copy(), random.Random(1), time_budget=20)
    assert sol.S >= start.S - 1e-9
    assert (sol.S > start.S + 1e-9) == (moves > 0)
    assert not check_plan(inst, sol)
    served = set(sol.truck_of)
    assert served.isdisjoint(sol.unassigned) and len(served) + len(sol.unassigned) == inst.n_orders
    rd = lambda n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8"))
    sc = loader.from_raw("x", rd("cities"), rd("trucks"), rd("orders"), rd("distance_matrix"))
    r = simulator.score(sc, sol.to_plan(inst))
    assert not r["validation"]["violations"]
    assert r["score"] == pytest.approx(sol.S, abs=1e-6)


def test_blockers_are_on_the_truck_and_early():
    folder = DIRS[0]
    inst = load_instance(folder)
    sol = construct(inst, seed=1, regret=1)
    for u in sol.unassigned:
        dl = ejection.deadline(inst, u)
        for k in ejection.solo_trucks(inst, u):
            on_truck = {oi for _, oi in sol.routes[k]}
            assert set(ejection.blockers(inst, sol, k, u)) <= on_truck
        assert dl is None or dl >= 0
