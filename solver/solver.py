"""
solver.py — Part C: the decision-maker.

    1. Binary decisions      every order is either assigned to one truck or not (y_rk ∈ {0,1})
    2. Feasibility           capacity, truck type, pickup-before-delivery, time windows (≤60 min late)
    3. Marginal score ΔS     for every feasible insertion: ΔS = S_new − S_old, take the best positive one
    4. Iterative improvement ALNS: remove some orders, re-insert them with ΔS, accept with simulated annealing

Signature idea: ΔS is computed on the *exact official score*, not on a km proxy,
so every decision is directly aligned with what the jury measures.
"""
from __future__ import annotations

import heapq
import math
import random
import time
from dataclasses import dataclass, field

from evaluator import EMPTY, Totals, TruckResult, score_swapped, score_value, simulate_truck
from instance import Instance

Stop = tuple[bool, int]          # (is_pickup, order_idx)


# ==========================================================================
# Solution
# ==========================================================================
@dataclass
class Solution:
    routes: list[list[Stop]]
    res: list[TruckResult]
    tot: Totals
    truck_of: dict[int, int]                  # order -> truck
    unassigned: set[int]
    S: float = 0.0

    @classmethod
    def empty(cls, inst: Instance) -> "Solution":
        n_t = len(inst.trucks)
        return cls([[] for _ in range(n_t)], [EMPTY] * n_t, Totals(), {}, set(range(inst.n_orders)), 0.0)

    def copy(self) -> "Solution":
        return Solution([r[:] for r in self.routes], self.res[:], self.tot.copy(),
                        dict(self.truck_of), set(self.unassigned), self.S)

    def set_route(self, inst: Instance, k: int, route: list[Stop], res: TruckResult | None = None) -> None:
        if res is None or (route and res.states is None):
            res = simulate_truck(inst, k, route, early_exit=False, record=True)
        self.tot.add(self.res[k], -1)
        self.tot.add(res, +1)
        self.routes[k] = route
        self.res[k] = res
        self.S = score_value(inst, self.tot)

    def to_plan(self, inst: Instance) -> dict:
        """Official submission format."""
        plan = {}
        for k, route in enumerate(self.routes):
            plan[inst.trucks[k].id] = [
                {"action": "pickup" if is_p else "delivery", "order": inst.orders[oi].id}
                for is_p, oi in route
            ]
        return plan


# ==========================================================================
# Insertion: candidate positions + exact ΔS
# ==========================================================================
@dataclass(slots=True)
class Insertion:
    dS: float
    k: int
    route: list[Stop]
    res: TruckResult


def _candidates(inst: Instance, route: list[Stop], k: int, oi: int, topk: int):
    """All capacity-feasible (a, b) positions, ranked by extra km; return the best `topk`.

    The route visits cities c[0]=start, c[1..m]. Pickup goes after c[a], delivery after c[b], a ≤ b.
    """
    t = inst.trucks[k]
    o = inst.orders[oi]
    D = inst.D
    orders = inst.orders
    m = len(route)
    c = [t.start] + [orders[x].p if is_p else orders[x].d for is_p, x in route]
    L = [0.0] * (m + 1)                       # load after position s
    load = 0.0
    for s, (is_p, x) in enumerate(route, 1):
        load += orders[x].weight if is_p else -orders[x].weight
        L[s] = load
    cap = t.capacity - o.weight + 1e-9
    P, Q = o.p, o.d
    DP, DQ = D[P], D[Q]
    # extra km to visit P (resp. Q) right after position s
    insP = [DP[c[s]] + DP[c[s + 1]] - D[c[s]][c[s + 1]] for s in range(m)] + [DP[c[m]]]
    insQ = [DQ[c[s]] + DQ[c[s + 1]] - D[c[s]][c[s + 1]] for s in range(m)] + [DQ[c[m]]]
    dPQ = DP[Q]
    cands = []
    for a in range(m + 1):
        if L[a] > cap:
            continue
        # delivery right after pickup
        dk = DP[c[a]] + dPQ + (DQ[c[a + 1]] - D[c[a]][c[a + 1]] if a < m else 0.0)
        cands.append((dk, a, a))
        ip = insP[a]
        running = L[a]
        for b in range(a + 1, m + 1):
            lb = L[b]
            if lb > running:
                if lb > cap:
                    break                     # the load window only grows → stop
                running = lb
            cands.append((ip + insQ[b], a, b))
    if len(cands) > topk:
        return heapq.nsmallest(topk, cands)
    return cands


def best_insertion(inst: Instance, sol: Solution, oi: int, k: int, topk: int) -> Insertion | None:
    """Best feasible way to put order oi into truck k, judged by exact ΔS."""
    route = sol.routes[k]
    base = sol.res[k]
    tot, S = sol.tot, sol.S
    # stops after the last time-window stop cannot change value: their clock is not simulated
    O = inst.orders
    lt = len(route) - 1
    while lt >= 0 and (O[route[lt][1]].ptw if route[lt][0] else O[route[lt][1]].dtw) is None:
        lt -= 1
    best = None
    for _, a, b in _candidates(inst, route, k, oi, topk):
        new_route = route[:a] + [(True, oi)] + route[a:b] + [(False, oi)] + route[b:]
        r = simulate_truck(inst, k, new_route, base=base, start=a, stop=(b if b > lt else lt) + 3)
        if not r.feasible:
            continue
        dS = score_swapped(inst, tot, base, r) - S
        if best is None or dS > best.dS:
            best = Insertion(dS, k, new_route, r)
    return best


def _near_trucks(inst: Instance, sol: Solution, oi: int, n: int | None) -> list[int]:
    """The n compatible trucks whose route (or start) passes closest to the order's pickup."""
    comp = inst.compatible[oi]
    if n is None or len(comp) <= n:
        return comp
    D, O, p = inst.D, inst.orders, inst.orders[oi].p
    row = D[p]

    def prox(k):
        best = row[inst.trucks[k].start]
        for is_p, x in sol.routes[k]:
            c = O[x].p if is_p else O[x].d
            if row[c] < best:
                best = row[c]
        return best
    return sorted(comp, key=prox)[:n]


def insert_orders(inst: Instance, sol: Solution, orders: list[int], rng: random.Random,
                  regret: int = 1, topk: int = 6, noise: float = 0.0,
                  max_trucks: int | None = None) -> None:
    """Greedy (regret=1) or regret-k insertion with exact marginal score ΔS.

    Cache: the best insertion of (order, truck) only changes when that truck's route
    changes, so after each insertion we recompute only the affected truck.
    ΔS itself is re-evaluated exactly against the current totals every round.
    """
    pending = [o for o in orders if o in sol.unassigned]
    cache: dict[tuple[int, int], Insertion | None] = {}
    O = inst.orders
    trucks_of = {oi: _near_trucks(inst, sol, oi, max_trucks) for oi in pending}
    while pending:
        pick = None          # (key, order, Insertion)
        for oi in pending:
            opts = []
            # time-window orders need early slots, which are rarely the cheapest in km
            tk = topk * 4 if (O[oi].ptw or O[oi].dtw) else topk
            for k in trucks_of[oi]:
                key = (oi, k)
                if key not in cache:
                    cache[key] = best_insertion(inst, sol, oi, k, tk)
                ins = cache[key]
                if ins is None:
                    continue
                dS = score_swapped(inst, sol.tot, sol.res[k], ins.res) - sol.S
                if noise:
                    dS *= 1.0 + noise * (2 * rng.random() - 1)
                opts.append((dS, ins))
            if not opts:
                continue
            opts.sort(key=lambda x: -x[0])
            best_dS, best_ins = opts[0]
            if best_dS <= 0:
                continue                         # only positive improvements
            if regret <= 1:
                key = best_dS
            else:
                # regret-k: how much we lose by not inserting this order now
                key = sum(best_dS - opts[i][0] if i < len(opts) else best_dS for i in range(1, regret))
                key = (key, best_dS)
            if pick is None or key > pick[0]:
                pick = (key, oi, best_ins)
        if pick is None:
            break
        _, oi, ins = pick
        sol.set_route(inst, ins.k, ins.route, ins.res)
        sol.truck_of[oi] = ins.k
        sol.unassigned.discard(oi)
        pending.remove(oi)
        for o2 in pending:
            cache.pop((o2, ins.k), None)


def remove_orders(inst: Instance, sol: Solution, orders: list[int]) -> None:
    by_truck: dict[int, set[int]] = {}
    for oi in orders:
        k = sol.truck_of.pop(oi, None)
        if k is not None:
            by_truck.setdefault(k, set()).add(oi)
            sol.unassigned.add(oi)
    for k, rm in by_truck.items():
        sol.set_route(inst, k, [s for s in sol.routes[k] if s[1] not in rm])


# ==========================================================================
# Construction
# ==========================================================================
def construct(inst: Instance, seed: int = 0, regret: int = 1, topk: int = 6) -> Solution:
    """Initial plan: insert orders one by one, always the feasible insertion with the highest ΔS."""
    sol = Solution.empty(inst)
    rng = random.Random(seed)
    O = inst.orders
    # phase 1: orders with time windows, by regret-3: an order that fits on only one truck
    # goes in first, before an easier order takes that truck's early slot
    tw = [o.idx for o in O if o.ptw or o.dtw]
    insert_orders(inst, sol, tw, rng, regret=3, topk=topk)
    # phase 2: everything else, always the highest ΔS first (regret if requested)
    insert_orders(inst, sol, list(sol.unassigned), rng, regret=regret, topk=topk)
    return sol


# ==========================================================================
# ALNS — destroy operators
# ==========================================================================
def d_random(inst, sol, q, rng):
    assigned = list(sol.truck_of)
    return rng.sample(assigned, min(q, len(assigned)))


def d_worst(inst, sol, q, rng, p=3.0):
    """Remove orders whose removal costs the fewest points (expensive per unit of value)."""
    loss = []
    for oi, k in sol.truck_of.items():
        route = sol.routes[k]
        first = next(i for i, s in enumerate(route) if s[1] == oi)
        r = simulate_truck(inst, k, [s for s in route if s[1] != oi], base=sol.res[k], start=first)
        loss.append((sol.S - score_value(inst, sol.tot.swapped(sol.res[k], r)), oi))
    loss.sort()
    out = []
    while loss and len(out) < q:
        out.append(loss.pop(int(len(loss) * rng.random() ** p))[1])
    return out


def d_shaw(inst, sol, q, rng, p=4.0):
    """Remove orders that are related (close pickups and deliveries, similar type/time):
    they are the ones that can be re-consolidated together."""
    assigned = list(sol.truck_of)
    if not assigned:
        return []
    D, O = inst.D, inst.orders
    maxd = max(max(row) for row in D) or 1.0

    def rel(i, j):
        a, b = O[i], O[j]
        r = (D[a.p][b.p] + D[a.d][b.d]) / maxd
        if a.required_type != b.required_type:
            r += 0.5
        return r

    out = [rng.choice(assigned)]
    rest = [o for o in assigned if o != out[0]]
    while rest and len(out) < q:
        ref = rng.choice(out)
        rest.sort(key=lambda j: rel(ref, j))
        out.append(rest.pop(int(len(rest) * rng.random() ** p)))
    return out


def d_route(inst, sol, q, rng):
    """Empty whole trucks — kills expensive/dirty trucks and long empty repositioning."""
    used = [k for k in range(len(inst.trucks)) if sol.routes[k]]
    rng.shuffle(used)
    # prefer trucks with high cost per unit of delivered value
    used.sort(key=lambda k: -(sol.res[k].cost / (sol.res[k].value + 1e-9)) * (0.5 + rng.random()))
    out = []
    for k in used:
        if len(out) >= q:
            break
        out.extend({oi for _, oi in sol.routes[k]})
    return out


def d_empty_leg(inst, sol, q, rng):
    """Remove the orders next to the longest empty drives."""
    legs = []
    O, D = inst.orders, inst.D
    for k, route in enumerate(sol.routes):
        city, load = inst.trucks[k].start, 0.0
        for is_p, oi in route:
            dest = O[oi].p if is_p else O[oi].d
            if load == 0 and D[city][dest] > 0:
                legs.append((D[city][dest] * (0.7 + 0.6 * rng.random()), oi))
            load += O[oi].weight if is_p else -O[oi].weight
            city = dest
    legs.sort(reverse=True)
    out = []
    for _, oi in legs:
        if oi not in out:
            out.append(oi)
        if len(out) >= q:
            break
    return out


DESTROY = {"random": d_random, "worst": d_worst, "shaw": d_shaw, "route": d_route, "empty_leg": d_empty_leg}
REPAIR = {
    "greedy": dict(regret=1, noise=0.0),
    "greedy_noise": dict(regret=1, noise=0.1),
    "regret2": dict(regret=2, noise=0.0),
    "regret3": dict(regret=3, noise=0.0),
}


# ==========================================================================
# ALNS — main loop
# ==========================================================================
@dataclass
class ALNSLog:
    history: list[tuple[int, float, float]] = field(default_factory=list)   # (iteration, seconds, best S)
    destroy_stats: dict = field(default_factory=dict)
    repair_stats: dict = field(default_factory=dict)
    iterations: int = 0


def alns(inst: Instance, start: Solution, time_limit: float = 60.0, seed: int = 0,
         topk: int = 3, max_trucks: int | None = 8, bank_retry: int = 8, segment: int = 50, reaction: float = 0.2,
         sigma=(33.0, 9.0, 13.0), t_start_pct: float = 0.005, t_end: float = 0.01,
         verbose: bool = True, max_iters: int | None = None) -> tuple[Solution, ALNSLog]:
    """Adaptive Large Neighbourhood Search (Ropke & Pisinger 2006) on the exact score.

    - destroy q orders, repair with ΔS insertion (all unassigned orders are retried too)
    - accept by simulated annealing: worse plans accepted with prob exp(ΔS / T)
    - operator weights adapt to how often each operator finds improvements
    """
    rng = random.Random(seed)
    cur, best = start.copy(), start.copy()
    log = ALNSLog()
    log.history.append((0, 0.0, best.S))
    dn, rn = list(DESTROY), list(REPAIR)
    w_d, w_r = {d: 1.0 for d in dn}, {r: 1.0 for r in rn}
    sc_d, sc_r = {d: 0.0 for d in dn}, {r: 0.0 for r in rn}
    ct_d, ct_r = {d: 0 for d in dn}, {r: 0 for r in rn}
    stats_d = {d: {"used": 0, "best": 0, "better": 0, "accepted": 0} for d in dn}
    stats_r = {r: {"used": 0, "best": 0, "better": 0, "accepted": 0} for r in rn}

    # temperature: a plan t_start_pct worse than the start is accepted with prob 0.5
    T0 = max(1e-6, t_start_pct * max(start.S, 1.0) / math.log(2))
    t0 = time.time()
    it = 0
    n = inst.n_orders
    q_min, q_max = max(2, int(0.05 * n)), max(4, min(40, int(0.3 * n)))

    while True:
        el = time.time() - t0
        if el >= time_limit or (max_iters is not None and it >= max_iters):
            break
        it += 1
        T = T0 * (t_end / T0) ** (el / time_limit) if T0 > t_end else t_end
        d = rng.choices(dn, weights=[w_d[x] for x in dn])[0]
        r = rng.choices(rn, weights=[w_r[x] for x in rn])[0]
        q = rng.randint(q_min, q_max)

        cand = cur.copy()
        bank = [o for o in cand.unassigned]
        removed = DESTROY[d](inst, cand, q, rng)
        remove_orders(inst, cand, removed)
        to_insert = removed + rng.sample(bank, min(bank_retry, len(bank)))
        rng.shuffle(to_insert)
        insert_orders(inst, cand, to_insert, rng, topk=topk, max_trucks=max_trucks, **REPAIR[r])

        stats_d[d]["used"] += 1; stats_r[r]["used"] += 1
        gain = 0.0
        if cand.S > best.S + 1e-9:
            best, cur, gain = cand.copy(), cand, sigma[0]
            stats_d[d]["best"] += 1; stats_r[r]["best"] += 1
            log.history.append((it, round(el, 2), best.S))
            if verbose:
                print(f"  it {it:5d}  {el:6.1f}s  new best {best.S:8.2f}  ({d} + {r}, q={q})")
        elif cand.S > cur.S + 1e-9:
            cur, gain = cand, sigma[1]
            stats_d[d]["better"] += 1; stats_r[r]["better"] += 1
        elif rng.random() < math.exp((cand.S - cur.S) / T):
            cur, gain = cand, sigma[2]
            stats_d[d]["accepted"] += 1; stats_r[r]["accepted"] += 1

        sc_d[d] += gain; sc_r[r] += gain
        ct_d[d] += 1; ct_r[r] += 1
        if it % segment == 0:
            for x in dn:
                if ct_d[x]:
                    w_d[x] = (1 - reaction) * w_d[x] + reaction * sc_d[x] / ct_d[x]
                w_d[x] = max(w_d[x], 0.05); sc_d[x] = 0; ct_d[x] = 0
            for x in rn:
                if ct_r[x]:
                    w_r[x] = (1 - reaction) * w_r[x] + reaction * sc_r[x] / ct_r[x]
                w_r[x] = max(w_r[x], 0.05); sc_r[x] = 0; ct_r[x] = 0

    log.iterations = it
    log.history.append((it, round(time.time() - t0, 2), best.S))
    for x in dn:
        stats_d[x]["final_weight"] = round(w_d[x], 3)
    for x in rn:
        stats_r[x]["final_weight"] = round(w_r[x], 3)
    log.destroy_stats, log.repair_stats = stats_d, stats_r
    return best, log


# ==========================================================================
# Safety: structural check before anything leaves the laptop
# ==========================================================================
def check_plan(inst: Instance, sol: Solution) -> list[str]:
    """Returns a list of problems; empty list = 0 violations by our own rules."""
    issues = []
    seen: dict[int, int] = {}
    for k, route in enumerate(sol.routes):
        t = inst.trucks[k]
        picked, delivered, load = set(), set(), 0.0
        for is_p, oi in route:
            o = inst.orders[oi]
            if is_p:
                if oi in picked:
                    issues.append(f"duplicate_pickup {o.id}")
                if oi in seen and seen[oi] != k:
                    issues.append(f"order_assigned_multiple_times {o.id}")
                seen[oi] = k
                picked.add(oi)
                load += o.weight
                if load > t.capacity + 1e-9:
                    issues.append(f"capacity_exceeded {t.id} at {o.id}")
                if o.required_type and o.required_type != t.type:
                    issues.append(f"truck_type_mismatch {o.id} on {t.id}")
            else:
                if oi not in picked:
                    issues.append(f"delivery_before_pickup {o.id}")
                if oi in delivered:
                    issues.append(f"duplicate_delivery {o.id}")
                delivered.add(oi)
                load -= o.weight
        for oi in picked - delivered:
            issues.append(f"pickup_without_delivery {inst.orders[oi].id}")
    return issues
