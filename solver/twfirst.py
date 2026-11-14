"""
twfirst.py — decide the time-window orders first, then build the plan around them.

Time-window orders are the scarce part of the problem: each can be served by few trucks, early
in their routes. Here they are solved as their own small problem with one goal (serve as much
time-window value as possible, km only as a tie-breaker), using the same exact time simulation.
The other orders are then inserted around that skeleton with the normal exact-score insertion.

    build(inst, time_limit, seed) -> (plan for the full instance, set of skeleton orders)
"""
from __future__ import annotations

import random

from instance import Instance, Order, precompute
from solver import Solution, alns, construct, insert_orders


def tw_subinstance(inst: Instance) -> tuple[Instance, list[int]]:
    """Instance with only the time-window orders, judged by value served. Returns (sub, sub idx -> full idx)."""
    full = [o.idx for o in inst.orders if o.ptw or o.dtw]
    sub = Instance(inst.city_ids, inst.city_names, inst.lat, inst.lon, inst.D, inst.trucks,
                   [Order(i, inst.orders[f].id, inst.orders[f].p, inst.orders[f].d, inst.orders[f].weight,
                          inst.orders[f].required_type, inst.orders[f].value, inst.orders[f].ptw,
                          inst.orders[f].dtw) for i, f in enumerate(full)])
    precompute(sub)
    sub.value_only = True
    # 1000 points for all value; serving one order alone (about 2 direct trips of km) costs
    # about one tenth of an average order's worth, so km only decide between near-equal plans
    mean_direct = sub.direct_km_total / max(1, sub.n_orders)
    sub.km_weight = 0.05 * (1000.0 / max(1, sub.n_orders)) / max(1.0, mean_direct)
    return sub, full


def skeleton(inst: Instance, time_limit: float, seed: int) -> Solution:
    """Plan for the full instance that contains only time-window orders (the rest unassigned)."""
    sol = Solution.empty(inst)
    sub, full = tw_subinstance(inst)
    if not full:
        return sol
    start = max((construct(sub, seed=seed, regret=rg) for rg in (1, 3)), key=lambda v: v.S)
    best, _ = alns(sub, start, time_limit=time_limit, seed=seed, verbose=False, max_trucks=None, topk=8)
    for k, route in enumerate(best.routes):
        if route:
            sol.set_route(inst, k, [(is_p, full[oi]) for is_p, oi in route])
            for _, oi in route:
                sol.truck_of[full[oi]] = k
                sol.unassigned.discard(full[oi])
    return sol


def build(inst: Instance, time_limit: float, seed: int) -> tuple[Solution, set[int]]:
    """Skeleton of time-window orders, then all other orders inserted by exact score gain."""
    sol = skeleton(inst, time_limit, seed)
    protect = set(sol.truck_of)
    rng = random.Random(seed)
    insert_orders(inst, sol, list(sol.unassigned), rng, regret=1, topk=6)
    return sol, protect
