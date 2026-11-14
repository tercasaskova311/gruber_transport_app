"""Why are orders missing from a plan? Uses the exact simulator only.

  python -m tools.missed_orders <scenario> <plan.json> [--snapshot TS]

For every unfulfilled order:
  - compatible trucks (type + capacity)
  - trucks that can serve it ALONE on time / within 60 min (from their start, empty route)
  - best insertion into each compatible truck's CURRENT route that keeps every order already
    on that truck fulfilled at no less value, and the resulting score change
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from gruber import loader, simulator


def P(o): return {"action": "pickup", "order": o}
def D(o): return {"action": "delivery", "order": o}


def truck_value(sc, tid, stops):
    """(violations, fulfilled order->value factor, finish) for one truck route."""
    sim = simulator.simulate(sc, {tid: stops})
    return sim["validation"]["violations"], sim["_fulfilled"], sim["metrics"]


def analyse(sc, plan):
    base = simulator.score(sc, plan)
    base_score = base["score"]
    fulfilled = set(base["_fulfilled"]) if "_fulfilled" in base else set(simulator.simulate(sc, plan)["_fulfilled"])
    missed = [o for o in sc.orders if o.id not in fulfilled]
    onboard = {tid: {s["order"] for s in stops} for tid, stops in plan.items()}
    rows = []
    for o in missed:
        compat = [t for t in sc.trucks if (o.required_type in (None, t.type)) and o.weight <= t.capacity]
        solo_ok, solo_late = [], []
        for t in compat:
            v, ful, _ = truck_value(sc, t.id, [P(o.id), D(o.id)])
            if o.id in ful:
                (solo_ok if ful[o.id] == 1.0 else solo_late).append(t.id)
        best = None            # (dscore, truck, i, j)
        n_feasible = 0
        for t in compat:
            route = plan.get(t.id, [])
            _, old_ful, _ = truck_value(sc, t.id, route)
            n = len(route)
            for i in range(n + 1):
                for j in range(i, n + 1):
                    new = route[:i] + [P(o.id)] + route[i:j] + [D(o.id)] + route[j:]
                    v, ful, _ = truck_value(sc, t.id, new)
                    if v or o.id not in ful:
                        continue
                    if any(ful.get(x, 0) < f - 1e-12 for x, f in old_ful.items()):
                        continue          # would drop or devalue an order already on this truck
                    n_feasible += 1
                    p2 = dict(plan); p2[t.id] = new
                    ds = simulator.score(sc, p2)["score"] - base_score
                    if best is None or ds > best[0]:
                        best = (ds, t.id, i, j)
        if not compat:
            reason = "no truck can carry it"
        elif not solo_ok and not solo_late:
            reason = "no truck reaches it in time even alone"
        elif best is None:
            reason = "fits alone, but no insertion into current routes keeps others intact"
        elif best[0] > 0:
            reason = "FREE GAIN: insertion exists and raises the score"
        else:
            reason = "insertion exists but lowers the score"
        rows.append(dict(order=o.id, type=o.required_type or "-", weight=o.weight, value=o.value,
                         pw=o.pw, dw=o.dw, n_compat=len(compat), solo_on_time=solo_ok,
                         solo_late=solo_late, n_insertions=n_feasible,
                         best=None if best is None else dict(dscore=round(best[0], 3), truck=best[1],
                                                            i=best[2], j=best[3]),
                         reason=reason))
    return base_score, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario"); ap.add_argument("plan"); ap.add_argument("--snapshot")
    ap.add_argument("--json", help="write details to this file")
    a = ap.parse_args()
    sc = loader.load(a.scenario, a.snapshot)
    plan = json.load(open(a.plan))
    base, rows = analyse(sc, plan)
    print(f"{a.scenario}: score {base:.2f}, {len(rows)} orders not fulfilled\n")
    print(f"{'order':6} {'type':12} {'kg':>6} {'val':>4} {'pickup win':>12} {'deliv win':>12} "
          f"{'fit':>3} {'solo':>4} {'ins':>5}  best insertion         reason")
    for r in rows:
        pw = f"{r['pw'][0]}-{r['pw'][1]}" if r["pw"] else "-"
        dw = f"{r['dw'][0]}-{r['dw'][1]}" if r["dw"] else "-"
        b = f"{r['best']['truck']} {r['best']['dscore']:+.2f}" if r["best"] else "-"
        print(f"{r['order']:6} {r['type']:12} {r['weight']:6} {r['value']:4} {pw:>12} {dw:>12} "
              f"{r['n_compat']:3} {len(r['solo_on_time']):4} {r['n_insertions']:5}  {b:22} {r['reason']}")
    print()
    for k, v in Counter(r["reason"] for r in rows).most_common():
        print(f"{v:3}  {k}")
    print("by type:", dict(Counter(r["type"] for r in rows)),
          "| with window:", sum(1 for r in rows if r["pw"] or r["dw"]), "of", len(rows))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
