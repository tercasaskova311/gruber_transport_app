"""solver/sisr.py: string removal never splits a pickup-delivery pair, blink repair keeps plans
valid and exactly scored, and the default search does not use the new operators."""
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "solver"))

import sisr  # noqa: E402
from instance import load_instance  # noqa: E402
from solver import alns, check_plan, construct, remove_orders  # noqa: E402

from simulator import loader, simulator  # noqa: E402

DIRS = [ROOT / "data" / "fake" / "fake_big_a"] + loader.list_snapshots("scenario_middle")[-1:]


@pytest.fixture(scope="module", params=DIRS, ids=lambda p: p.parent.name + "/" + p.name)
def case(request):
    inst = load_instance(request.param)
    return request.param, inst, construct(inst, seed=1)


def exact(folder, plan):
    rd = lambda n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8"))
    sc = loader.from_raw("x", rd("cities"), rd("trucks"), rd("orders"), rd("distance_matrix"))
    return simulator.score(sc, plan)


def test_string_removal(case):
    _, inst, start = case
    rng = random.Random(3)
    sizes = []
    for q in (2, 5, 10, 20, 36) * 20:
        sol = start.copy()
        removed = sisr.d_string(inst, sol, q, rng)
        assert removed and len(set(removed)) == len(removed)
        assert all(o in sol.truck_of for o in removed)          # only served orders
        assert len(removed) < q + sisr.L_MAX                    # stays near the requested size
        sizes.append(len(removed))
        remove_orders(inst, sol, removed)
        assert not check_plan(inst, sol)                        # no half orders left on any route
        for route in sol.routes:
            assert not {oi for _, oi in route} & set(removed)
    assert max(sizes) > 5                                       # more than one string is used


def test_blink_repair_is_valid_and_exact(case):
    folder, inst, start = case
    rng = random.Random(5)
    sol = start.copy()
    for _ in range(15):
        removed = sisr.d_string(inst, sol, 12, rng)
        remove_orders(inst, sol, removed)
        sisr.blink_insert(inst, sol, removed + list(sol.unassigned), rng, topk=3, max_trucks=8)
        assert not check_plan(inst, sol)
    r = exact(folder, sol.to_plan(inst))
    assert not r["validation"]["violations"]
    assert r["score"] == pytest.approx(sol.S, abs=1e-6)


@pytest.mark.parametrize("kw,destroy,repair", [
    ({}, None, None),
    ({"sisr": True}, "string", "blink"),
    ({"sisr_only": True}, "string", "blink"),
])
def test_alns_switches(case, kw, destroy, repair):
    folder, inst, start = case
    best, log = alns(inst, start, time_limit=1e9, max_iters=60, seed=2, verbose=False, **kw)
    assert not check_plan(inst, best) and best.S >= start.S - 1e-9
    if destroy is None:                                         # default: the new operators do not exist
        assert "string" not in log.destroy_stats and "blink" not in log.repair_stats
    else:
        assert log.destroy_stats[destroy]["used"] > 0 and log.repair_stats[repair]["used"] > 0
    if kw.get("sisr_only"):
        assert list(log.destroy_stats) == ["string"] and list(log.repair_stats) == ["blink"]
    r = exact(folder, best.to_plan(inst))
    assert not r["validation"]["violations"]
    assert r["score"] == pytest.approx(best.S, abs=1e-6)
