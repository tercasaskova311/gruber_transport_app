"""
ejection.py — make room for unserved time-window orders.

An unserved order with a time window usually has a truck that could reach it on time, but
that truck is busy at that hour. Two tools, both generic (they only look at the instance and
the current plan):

  eject_sweep   local search: for an unserved order u and a truck k, take 1-2 orders off k
                that have a stop before u's window closes ("blockers"), insert u, then put the
                ejected orders back anywhere (if one does not fit, it may eject once more:
                depth 2). The move is kept only if the exact total score rises.

  d_block       ALNS destroy operator: pick a few unserved orders, clear the blockers from a
                truck that can reach each of them, and let the repair step rebuild with the
                unserved orders inserted first.

The case "insert u without ejecting anything" is deliberately not handled here (that is the
unassigned-pool sweep, built separately).
"""
from __future__ import annotations

import random
import time

from evaluator import simulate_truck
from instance import Instance
from solver import Solution, best_insertion, insert_orders, remove_orders


def deadline(inst: Instance, u: int) -> float | None:
    """Latest minute at which a truck can still leave for u's pickup and be at most 60 min late
    (ignoring breaks). None if u has no time window."""
    o = inst.orders[u]
    dl = None
    if o.ptw is not None:
        dl = o.ptw[1] + 60
    if o.dtw is not None:
        x = o.dtw[1] + 60 - inst.M[o.p][o.d] - 30
        dl = x if dl is None or x < dl else dl
    return dl


def solo_trucks(inst: Instance, u: int) -> list[int]:
    """Compatible trucks that fulfil u when they serve it alone, straight from their start."""
    cache = inst.__dict__.setdefault("_solo", {})
    if u not in cache:
        cache[u] = [k for k in inst.compatible[u]
                    if simulate_truck(inst, k, [(True, u), (False, u)]).feasible]
    return cache[u]


def blockers(inst: Instance, sol: Solution, k: int, u: int) -> list[int]:
    """Orders on truck k with a stop that starts before u's deadline, earliest first."""
    dl = deadline(inst, u)
    if dl is None:
        return []
    states = sol.res[k].states
    out = []
    for i, (_, oi) in enumerate(sol.routes[k]):
        if states[i][1] + inst.M[states[i][0]][inst.orders[u].p] > dl:
            break                   # the truck leaves stop i-1 too late to reach u: later stops don't block
        if oi not in out:
            out.append(oi)
    return out


def _try(inst: Instance, sol: Solution, u: int, k: int, eject: list[int], rng: random.Random,
         topk: int, depth: int) -> Solution | None:
    """Eject `eject` from truck k, insert u there, reinsert the ejected orders. None if u does not fit."""
    trial = sol.copy()
    remove_orders(inst, trial, eject)
    ins = best_insertion(inst, trial, u, k, topk)
    if ins is None:
        return None
    trial.set_route(inst, ins.k, ins.route, ins.res)
    trial.truck_of[u] = k
    trial.unassigned.discard(u)
    insert_orders(inst, trial, eject, rng, regret=1, topk=6, max_trucks=None)
    if depth > 1:
        for e in eject:
            if e in trial.unassigned:
                deeper = eject_move(inst, trial, e, rng, topk=topk, depth=depth - 1, forbid=u)
                if deeper is not None:
                    trial = deeper
    return trial


def eject_move(inst: Instance, sol: Solution, u: int, rng: random.Random, topk: int = 12,
               depth: int = 2, max_pair_pool: int = 5, forbid: int | None = None) -> Solution | None:
    """Best score-improving ejection move that brings unserved order u into the plan, or None."""
    best = None
    for k in solo_trucks(inst, u):
        if not sol.routes[k]:
            continue                # empty truck = plain insertion, not an ejection
        cand = [e for e in blockers(inst, sol, k, u) if e != forbid]
        fitted = False
        for e in cand:
            t = _try(inst, sol, u, k, [e], rng, topk, depth)
            if t is not None:
                fitted = True
                if t.S > sol.S + 1e-9 and (best is None or t.S > best.S):
                    best = t
        if not fitted:              # no single ejection makes room: try pairs of the earliest blockers
            pool = cand[:max_pair_pool]
            for i in range(len(pool)):
                for j in range(i + 1, len(pool)):
                    t = _try(inst, sol, u, k, [pool[i], pool[j]], rng, topk, depth)
                    if t is not None and t.S > sol.S + 1e-9 and (best is None or t.S > best.S):
                        best = t
    return best


def eject_sweep(inst: Instance, sol: Solution, rng: random.Random, time_budget: float = 5.0,
                depth: int = 2) -> tuple[Solution, int]:
    """Apply improving ejection moves for unserved time-window orders until none is left
    (or the time budget is used). Returns (plan, number of moves applied)."""
    t0 = time.time()
    moves = 0
    improved = True
    while improved:
        improved = False
        todo = [u for u in sol.unassigned if deadline(inst, u) is not None]
        rng.shuffle(todo)
        todo.sort(key=lambda u: -inst.orders[u].value)
        for u in todo:
            if time.time() - t0 > time_budget:
                return sol, moves
            if u not in sol.unassigned:
                continue
            new = eject_move(inst, sol, u, rng, depth=depth)
            if new is not None:
                sol = new
                moves += 1
                improved = True
    return sol, moves


def d_block(inst: Instance, sol: Solution, q: int, rng: random.Random) -> tuple[list[int], list[int]]:
    """Destroy operator: for a few unserved time-window orders, remove the blockers from one
    truck that could reach them. Returns (orders to remove, unserved orders to insert first)."""
    todo = [u for u in sol.unassigned if deadline(inst, u) is not None]
    if not todo:
        return [], []
    rng.shuffle(todo)
    removed: list[int] = []
    targets: list[int] = []
    for u in todo:
        trucks = [k for k in solo_trucks(inst, u) if sol.routes[k]]
        if not trucks:
            continue
        k = rng.choice(trucks)
        b = [e for e in blockers(inst, sol, k, u) if e not in removed]
        if not b:
            continue
        targets.append(u)
        removed.extend(b)
        if len(removed) >= q:
            break
    return removed[:max(q, 1)], targets
