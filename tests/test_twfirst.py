"""solver/twfirst.py: the skeleton-first start plan must be valid, protect only time-window
orders that are actually in the plan, and score the same in the exact simulator."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "solver"))

import twfirst  # noqa: E402
from instance import load_instance  # noqa: E402
from solver import check_plan  # noqa: E402

from simulator import loader, simulator  # noqa: E402

DIRS = [ROOT / "data" / "fake" / "fake_big_a"] + loader.list_snapshots("scenario_middle")[-1:]


@pytest.mark.parametrize("folder", DIRS, ids=lambda p: p.parent.name + "/" + p.name)
def test_build_is_valid_and_exact(folder):
    inst = load_instance(folder)
    sol, protect = twfirst.build(inst, time_limit=2, seed=1)
    assert not check_plan(inst, sol)
    assert not inst.value_only                      # the full instance keeps the real score
    assert all(inst.orders[o].ptw or inst.orders[o].dtw for o in protect)
    assert protect <= set(sol.truck_of)
    rd = lambda n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8"))
    sc = loader.from_raw("x", rd("cities"), rd("trucks"), rd("orders"), rd("distance_matrix"))
    r = simulator.score(sc, sol.to_plan(inst))
    assert not r["validation"]["violations"]
    assert r["score"] == pytest.approx(sol.S, abs=1e-6)


def test_subinstance_maps_back():
    inst = load_instance(DIRS[0])
    sub, full = twfirst.tw_subinstance(inst)
    assert sub.value_only and sub.n_orders == len(full)
    for i, f in enumerate(full):
        assert sub.orders[i].id == inst.orders[f].id
