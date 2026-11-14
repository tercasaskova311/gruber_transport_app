"""Polish a finished plan: small exact-score moves, keep only strict improvements.

  python -m tools.polish <snapshot_dir> <plan.json> --time 120 --seed 1 --out polished.json

Starts from the given plan (never from scratch) and repeats: take 1-3 orders out, put them back
at their best place on any compatible truck (wide search), keep the result only if the exact
score is higher. No order is ever dropped on purpose, so fulfilment cannot fall; what can improve
is empty km (loaded ratio) and lateness. The result is checked with the exact simulator.
No API calls.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "solver"))

from instance import load_instance  # noqa: E402
from solver import Solution, check_plan, d_shaw, insert_orders, remove_orders  # noqa: E402

from simulator import loader, simulator  # noqa: E402


def from_plan(inst, plan: dict) -> Solution:
    oid = {o.id: o.idx for o in inst.orders}
    sol = Solution.empty(inst)
    for k, t in enumerate(inst.trucks):
        route = [(s["action"] == "pickup", oid[s["order"]]) for s in plan.get(t.id, [])]
        if route:
            sol.set_route(inst, k, route)
            for _, oi in route:
                sol.truck_of[oi] = k
                sol.unassigned.discard(oi)
    return sol


def polish(inst, sol: Solution, time_limit: float, seed: int, topk: int = 12, verbose: bool = True) -> Solution:
    rng = random.Random(seed)
    t0 = time.time()
    tries = wins = 0
    singles: list[int] = []
    while time.time() - t0 < time_limit:
        kind = rng.random()
        if kind < 0.4:                                   # one order, each in turn
            if not singles:
                singles = list(sol.truck_of)
                rng.shuffle(singles)
            out = [singles.pop()]
        elif kind < 0.7:                                 # 2-3 orders with nearby stops
            out = d_shaw(inst, sol, rng.randint(2, 3), rng)
        elif kind < 0.9:                                 # 2-3 orders of one truck
            k = rng.choice([k for k, r in enumerate(sol.routes) if r])
            on = list({oi for _, oi in sol.routes[k]})
            out = rng.sample(on, min(len(on), rng.randint(2, 3)))
        else:                                            # the first order of a truck and the one after
            k = rng.choice([k for k, r in enumerate(sol.routes) if r])
            out = list(dict.fromkeys(oi for _, oi in sol.routes[k][:3]))[:2]
        out = [o for o in out if o in sol.truck_of]
        if not out:
            continue
        cand = sol.copy()
        remove_orders(inst, cand, out)
        todo = out + list(cand.unassigned - set(out))
        insert_orders(inst, cand, todo, rng, regret=rng.choice((1, 1, 2, 3)), topk=topk, max_trucks=None)
        tries += 1
        if cand.S > sol.S + 1e-9:
            wins += 1
            if verbose:
                print(f"  {time.time() - t0:6.1f}s  {sol.S:.4f} -> {cand.S:.4f}  (moved {len(out)})", flush=True)
            sol = cand
    if verbose:
        print(f"  {tries} moves tried, {wins} kept")
    return sol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("plan", type=Path)
    ap.add_argument("--time", type=float, default=120.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    inst = load_instance(a.folder)
    plan = json.loads(a.plan.read_text(encoding="utf-8"))
    rd = lambda n: json.loads((a.folder / f"{n}.json").read_text(encoding="utf-8"))
    sc = loader.from_raw("x", rd("cities"), rd("trucks"), rd("orders"), rd("distance_matrix"))
    before = simulator.score(sc, plan)
    sol = from_plan(inst, plan)
    assert abs(sol.S - before["score"]) < 1e-6, (sol.S, before["score"])
    print(f"start {before['score']:.4f}  {before['metrics']['orders_fulfilled']} orders  "
          f"loaded {before['breakdown']['loaded_ratio']:.3f}  late penalty {before['breakdown']['late_penalty']:.3f}")
    sol = polish(inst, sol, a.time, a.seed)
    assert not check_plan(inst, sol)
    out = sol.to_plan(inst)
    after = simulator.score(sc, out)
    assert not after["validation"]["violations"] and not after["_unverified"]
    assert abs(sol.S - after["score"]) < 1e-6
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"end   {after['score']:.4f}  {after['metrics']['orders_fulfilled']} orders  "
          f"loaded {after['breakdown']['loaded_ratio']:.3f}  late penalty {after['breakdown']['late_penalty']:.3f}  "
          f"(+{after['score'] - before['score']:.4f})  -> {a.out}")


if __name__ == "__main__":
    main()
