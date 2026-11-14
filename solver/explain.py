"""
explain.py: WHY is an order unserved? Answered by the exact evaluator, not guessed.

For every order a plan leaves out, we try to put it into every truck that may carry it
(the same exact insertion the solver uses, judged by the official score) and report the
first reason that applies:

    no_truck     no truck of the required type is big enough
    unreachable  even an EMPTY truck driving straight there is > 60 min late
    full         reachable, but every truck that could take it is booked: fitting it in
                 makes another delivery > 60 min late, or overloads the truck
    costs        it fits, but the score goes DOWN (the detour costs more than the order brings)
    missed       it fits and the score goes UP: the solver should have taken it

Then a what-if for the fleet: one extra truck (a copy of the biggest truck of the needed
type, parked where most of those orders start) and how many of them it would serve.

    python explain.py scenario_competitive          # best plan in results.runs
    python explain.py scenario_competitive plan.json

Standard library only (like solver.py / evaluator.py).
"""
from __future__ import annotations

import dataclasses
import json
import random
import sys
from collections import Counter

from evaluator import EMPTY, score_swapped, simulate_truck
from instance import Instance, precompute
from solver import Solution, _candidates, best_insertion, insert_orders

TOPK = 300          # insertion positions tried per truck, shortest detours first


def solution_from_plan(inst: Instance, plan: dict) -> Solution:
    """Rebuild the solver's Solution from an official plan {truck_id: [{action, order}, ...]}."""
    t_idx = {t.id: t.idx for t in inst.trucks}
    o_idx = {o.id: o.idx for o in inst.orders}
    sol = Solution.empty(inst)
    for tid, stops in plan.items():
        k = t_idx[tid]
        route = [(s["action"] == "pickup", o_idx[s["order"]]) for s in stops]
        sol.set_route(inst, k, route)
        for is_p, oi in route:
            if is_p:
                sol.truck_of[oi] = k
                sol.unassigned.discard(oi)
    return sol


def _clock(minutes: float) -> str:
    t = 360 + int(minutes)
    return f"Day {t // 1440 + 1} {t % 1440 // 60:02d}:{t % 60:02d}"


def why(inst: Instance, sol: Solution, oi: int) -> dict:
    """The reason one unserved order is unserved: {kind, text, truck, dS, detour_km}."""
    o = inst.orders[oi]
    need = o.required_type or "standard"
    comp = inst.compatible[oi]
    if not comp:
        same = [t for t in inst.trucks if o.required_type is None or t.type == o.required_type]
        if not same:
            return {"kind": "no_truck", "text": f"No {need} truck in the fleet"}
        big = max(t.capacity for t in same)
        return {"kind": "no_truck",
                "text": f"Too heavy: {o.weight / 1000:g} t, the biggest {need} truck carries {big / 1000:g} t"}

    # 1. can ANY compatible truck reach it in time when it does nothing else?
    alone = []
    for k in comp:
        r = simulate_truck(inst, k, [(True, oi), (False, oi)], early_exit=False)
        alone.append((r.late.get(oi, 0.0), k))
    late, k_near = min(alone)
    if late > 60:
        w = o.ptw if o.ptw else o.dtw
        where = "pickup" if o.ptw else "delivery"
        return {"kind": "unreachable", "truck": inst.trucks[k_near].id,
                "text": f"Out of reach: even driving there empty, the closest {need} truck "
                        f"({inst.trucks[k_near].id}) is {late / 60:.1f} h late for the {where} "
                        f"(window closes {_clock(w[1])})"}

    # 2. the exact best insertion into every compatible truck
    best = None
    for k in comp:
        ins = best_insertion(inst, sol, oi, k, TOPK)
        if ins is not None and (best is None or ins.dS > best.dS):
            best = ins
    if best is None:
        return _blocked(inst, sol, oi, [k for lm, k in alone if lm <= 60], need)
    tid = inst.trucks[best.k].id
    detour = best.res.km - sol.res[best.k].km
    if best.dS <= 0:
        return {"kind": "costs", "truck": tid, "dS": best.dS, "detour_km": detour,
                "text": f"Fits {tid} (+{detour:,.0f} km), but the score drops by {-best.dS:.1f}: "
                        f"the detour costs more than the order brings"}
    return {"kind": "missed", "truck": tid, "dS": best.dS, "detour_km": detour,
            "text": f"Fits {tid} (+{detour:,.0f} km) and the score goes up by {best.dS:.1f}: "
                    f"the solver missed it"}


def _blocked(inst: Instance, sol: Solution, oi: int, trucks: list[int], need: str) -> dict:
    """No truck can take the order without breaking a rule. Answer the dispatcher's question:
    what would it COST to do it on time? We try every slot in which a truck could still be on
    time (before its clock passes the deadline). Deliveries that become > 60 min late are lost,
    so we take them OUT of the route and score the swap exactly. Keep the best swap."""
    O, o = inst.orders, inst.orders[oi]
    deadline = (o.ptw[1] if o.ptw else o.dtw[1]) + 60
    cap = None
    best = None                                # (score change, truck, lost order ids)
    for k in trucks:
        route, states = sol.routes[k], sol.res[k].states
        for a in range(len(route) + 1):
            if states and states[a][1] > deadline:
                break                          # from here on the truck is past the deadline
            for b in range(a, min(a + 4, len(route)) + 1):   # deliver soon after the pickup
                new = route[:a] + [(True, oi)] + route[a:b] + [(False, oi)] + route[b:]
                r = simulate_truck(inst, k, new, early_exit=False)
                if r.late.get(oi, 0.0) > 60 or r.max_load > inst.trucks[k].capacity + 1e-9:
                    continue                   # this order still late, or the truck overloaded
                lost = {x for x, lm in r.late.items() if lm > 60 and x != oi}
                if lost:                       # the swap for real: lost orders leave the route
                    r = simulate_truck(inst, k, [st for st in new if st[1] not in lost], early_exit=False)
                    if not r.feasible:
                        continue
                dS = score_swapped(inst, sol.tot, sol.res[k], r) - sol.S
                if best is None or dS > best[0]:
                    best = (dS, k, [O[x].id for x in sorted(lost)])
    if best is not None:
        dS, k, lost = best
        tid = inst.trucks[k].id
        shown = ", ".join(lost[:2]) + (f" +{len(lost) - 2}" if len(lost) > 2 else "")
        swap = (f"{tid} could take it on time, but then {shown} {'is' if len(lost) == 1 else 'are'} lost"
                if lost else f"{tid} could take it on time")
        verdict = (f"score {dS:+.1f}: the solver missed this" if dS > 0 else f"score {dS:+.1f}, so not worth it")
        return {"kind": "missed" if dS > 0 else "full", "truck": tid, "blocks": lost, "dS": dS,
                "text": f"Every {need} truck is booked then. {swap} ({verdict})"}
    # no slot is on time: when is the first truck free?
    when = min((sol.res[k].finish_min, k) for k in trucks) if trucks else None
    text = f"Every {need} truck is busy elsewhere when this order must be picked up"
    if when:
        text += f" (window closes {_clock(deadline - 60)})"
    return {"kind": "full", "text": text}


def extra_truck(inst: Instance, sol: Solution, orders: list[int], truck_type: str) -> dict | None:
    """What one more truck of `truck_type` would do: a copy of the biggest such truck, parked
    in the pickup city of most of `orders`. Returns {start_city, served, dS, template} or None."""
    same = [t for t in inst.trucks if t.type == truck_type]
    if not same or not orders:
        return None
    tmpl = max(same, key=lambda t: (t.capacity, -t.cost_per_km))
    start = Counter(inst.orders[oi].p for oi in orders).most_common(1)[0][0]
    new = dataclasses.replace(tmpl, idx=len(inst.trucks), id="NEW", start=start)
    inst2 = dataclasses.replace(inst, trucks=inst.trucks + [new])
    precompute(inst2)            # same cheapest cost / CO2 per km: the score's references don't move
    sol2 = sol.copy()
    sol2.routes.append([])
    sol2.res.append(EMPTY)
    sol2.geo.append(None)
    before = sol2.S
    # the orders may also fit an existing truck once the new one exists: reported as also_fitted
    insert_orders(inst2, sol2, orders, random.Random(0), topk=TOPK, max_trucks=None)
    served = [oi for oi in orders if sol2.truck_of.get(oi) == new.idx]
    gained = [oi for oi in orders if oi in sol2.truck_of and sol2.truck_of[oi] != new.idx]
    return {"start_city": inst.city_names[start], "type": truck_type, "template": tmpl.id,
            "capacity_t": tmpl.capacity / 1000, "served": [inst.orders[oi].id for oi in served],
            "also_fitted": [inst.orders[oi].id for oi in gained], "dS": sol2.S - before}


def explain_plan(inst: Instance, plan: dict) -> dict:
    """{"orders": {order_id: why(...)}, "extra_trucks": [extra_truck(...), ...]}"""
    sol = solution_from_plan(inst, plan)
    reasons = {inst.orders[oi].id: why(inst, sol, oi) for oi in sorted(sol.unassigned)}
    # one what-if per truck type, for the orders an extra truck could actually help
    # (not the ones no truck can carry, nor the ones that already fit)
    by_type: dict[str, list[int]] = {}
    for oi in sorted(sol.unassigned):
        if reasons[inst.orders[oi].id]["kind"] in ("unreachable", "full", "costs"):
            by_type.setdefault(inst.orders[oi].required_type or "standard", []).append(oi)
    extras = [x for typ, ois in by_type.items() if (x := extra_truck(inst, sol, ois, typ)) and x["served"]]
    extras.sort(key=lambda x: -x["dS"])
    return {"orders": reasons, "extra_trucks": extras}


def main() -> None:
    import time
    from instance import load_from_db
    scenario = sys.argv[1] if len(sys.argv) > 1 else "scenario_competitive"
    inst = load_from_db(scenario)
    if len(sys.argv) > 2:
        plan = json.loads(open(sys.argv[2]).read())
    else:
        from ingestion import load as dl
        con = dl.connect()
        plan = json.loads(con.execute(
            "SELECT plan_json FROM results.runs WHERE scenario_id = ? "
            "ORDER BY n_violations = 0 DESC, score DESC LIMIT 1", [scenario]).fetchone()[0])
        con.close()
    t0 = time.time()
    out = explain_plan(inst, plan)
    for oid, r in out["orders"].items():
        print(f"{oid:6} {r['kind']:12} {r['text']}")
    for x in out["extra_trucks"]:
        print(f"+1 {x['type']} truck ({x['capacity_t']:g} t) at {x['start_city']}: "
              f"serves {len(x['served'])} ({', '.join(x['served'])}), score {x['dS']:+.1f}")
    print(f"({time.time() - t0:.1f} s)")


if __name__ == "__main__":
    main()
