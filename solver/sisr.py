"""
sisr.py — Slack Induction by String Removals (Christiaens & Vanden Berghe 2020), adapted to
pickup-and-delivery routes.

Two ALNS operators, both generic (they only look at the instance and the current plan):

  d_string      destroy: pick a seed stop, then walk over the stops nearest to it. In the route of
                each such stop (each truck at most once) cut out a "string" of consecutive stops
                that contains it. An order with a stop inside a string is removed completely
                (pickup and delivery), so pairs are never split. Removing neighbouring stretches
                of several routes at once leaves room ("slack") in the same region and time, so
                the removed orders can be recombined across those routes.

  blink_insert  repair: sort the orders by a random rule, then insert them one at a time at the
                best position by exact score gain, where each candidate position is skipped
                ("blink") with a small probability, so the second-best place is sometimes taken.

String sizes follow the paper: at most L_MAX stops per string, and the number of strings is
drawn so that about q orders are removed (q is the destroy size the ALNS asks for).
"""
from __future__ import annotations

import random

from evaluator import score_swapped, simulate_truck
from instance import Instance
from solver import Solution, _candidates, _near_trucks

L_MAX = 10          # longest string, in stops (paper: 10 customers)
SPLIT = 0.5         # chance of a "split string": a few stops inside the string stay in place
SPLIT_GROW = 0.1    # a split string keeps one more stop with probability 1 - SPLIT_GROW, repeatedly
BLINK = 0.01        # chance that a candidate position is skipped during repair (paper: 0.01)
SORTS = ("random", "random", "value", "weight", "window")   # order rules for repair, picked at random


def _near_stops(inst: Instance, city: int) -> list[tuple[bool, int]]:
    """All stops (is_pickup, order) of the instance, nearest to `city` first."""
    cache = inst.__dict__.setdefault("_near_stops", {})
    if city not in cache:
        row = inst.D[city]
        stops = [(row[o.p], True, o.idx) for o in inst.orders] + [(row[o.d], False, o.idx) for o in inst.orders]
        stops.sort()
        cache[city] = [(is_p, oi) for _, is_p, oi in stops]
    return cache[city]


def _string(m: int, i: int, length: int, rng: random.Random) -> tuple[int, int]:
    """Start and end (exclusive) of a window of `length` stops in a route of m stops that contains i."""
    lo, hi = max(0, i - length + 1), min(i, m - length)
    s = rng.randint(lo, hi)
    return s, s + length


def d_string(inst: Instance, sol: Solution, q: int, rng: random.Random) -> list[int]:
    """Destroy operator: remove strings of consecutive stops from several routes near a seed stop."""
    if not sol.truck_of:
        return []
    used = [r for r in sol.routes if r]
    avg = sum(len(r) for r in used) / len(used)
    l_max = max(1.0, min(L_MAX, avg))                       # longest string for this plan
    k_max = max(1.0, 4.0 * q / (1.0 + l_max) - 1.0)         # paper: 4c/(1+l) - 1, c = orders to remove
    n_strings = int(rng.uniform(1.0, k_max + 1.0))
    seed = rng.choice(list(sol.truck_of))
    o = inst.orders[seed]
    city = o.p if rng.random() < 0.5 else o.d
    removed: list[int] = []
    gone: set[int] = set()
    ruined: set[int] = set()
    for is_p, oi in _near_stops(inst, city):
        if len(ruined) >= n_strings or len(removed) >= q:
            break
        k = sol.truck_of.get(oi)
        if k is None or k in ruined or oi in gone:
            continue
        route = sol.routes[k]
        m = len(route)
        i = route.index((is_p, oi))
        length = int(rng.uniform(1.0, min(m, l_max) + 1.0))
        keep: range = range(0)
        if length < m and rng.random() < SPLIT:             # split string: skip a few stops in the middle
            extra = 1
            while length + extra < m and rng.random() > SPLIT_GROW:
                extra += 1
            a, b = _string(m, i, length + extra, rng)
            ks = rng.randint(a, b - extra)
            keep = range(ks, ks + extra)
            if i in keep:                                    # the seed stop itself must go
                keep = range(0)
                a, b = _string(m, i, length, rng)
        else:
            a, b = _string(m, i, length, rng)
        for s in range(a, b):
            if s in keep:
                continue
            x = route[s][1]
            if x not in gone:
                gone.add(x)
                removed.append(x)
        ruined.add(k)
    return removed


def _blink_best(inst: Instance, sol: Solution, oi: int, k: int, topk: int, rng: random.Random, blink: float):
    """Best position for order oi on truck k by exact score gain, skipping each candidate with prob. blink."""
    route = sol.routes[k]
    base = sol.res[k]
    O = inst.orders
    lt = len(route) - 1
    while lt >= 0 and (O[route[lt][1]].ptw if route[lt][0] else O[route[lt][1]].dtw) is None:
        lt -= 1
    best = None
    for _, a, b in _candidates(inst, sol, k, oi, topk):
        if rng.random() < blink:
            continue
        new_route = route[:a] + [(True, oi)] + route[a:b] + [(False, oi)] + route[b:]
        r = simulate_truck(inst, k, new_route, base=base, start=a, stop=(b if b > lt else lt) + 3)
        if not r.feasible:
            continue
        dS = score_swapped(inst, sol.tot, base, r) - sol.S
        if best is None or dS > best[0]:
            best = (dS, k, new_route, r)
    return best


def blink_insert(inst: Instance, sol: Solution, orders: list[int], rng: random.Random, topk: int = 6,
                 max_trucks: int | None = None, blink: float = BLINK) -> None:
    """Repair operator: greedy insertion with blinks, one order at a time in a randomly chosen order."""
    pending = list(dict.fromkeys(o for o in orders if o in sol.unassigned))     # each order once
    rng.shuffle(pending)
    O = inst.orders
    rule = rng.choice(SORTS)
    if rule == "value":
        pending.sort(key=lambda x: -O[x].value)
    elif rule == "weight":
        pending.sort(key=lambda x: -O[x].weight)
    elif rule == "window":
        pending.sort(key=lambda x: 0 if (O[x].ptw or O[x].dtw) else 1)
    for oi in pending:
        tk = topk * 4 if (O[oi].ptw or O[oi].dtw) else topk     # as in insert_orders
        best = None
        for k in _near_trucks(inst, sol, oi, max_trucks):
            ins = _blink_best(inst, sol, oi, k, tk, rng, blink)
            if ins is not None and (best is None or ins[0] > best[0]):
                best = ins
        if best is None or best[0] <= 0:
            continue                                            # only positive improvements
        _, k, route, res = best
        sol.set_route(inst, k, route, res)
        sol.truck_of[oi] = k
        sol.unassigned.discard(oi)
