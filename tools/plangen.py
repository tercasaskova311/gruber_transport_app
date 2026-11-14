"""Random plan generators used for parity testing against the API."""
from __future__ import annotations

import random

from simulator.loader import Scenario


def compatible(sc: Scenario, o, t) -> bool:
    return (o.required_type is None or o.required_type == t.type) and o.weight <= t.capacity


def _insert(rng, route, o, cap, wmap, consolidate: bool):
    """Insert pickup/delivery of order o into route (list of (action, oid))."""
    if consolidate and route:
        n = len(route)
        for _ in range(20):
            i = rng.randint(0, n)
            j = rng.randint(i, n)
            cand = route[:i] + [("pickup", o.id)] + route[i:j] + [("delivery", o.id)] + route[j:]
            load, ok = 0, True
            for a, oid in cand:
                load += wmap[oid] if a == "pickup" else -wmap[oid]
                if load > cap:
                    ok = False
                    break
            if ok:
                return cand
    return route + [("pickup", o.id), ("delivery", o.id)]


def random_valid_plan(sc: Scenario, rng: random.Random, frac: float = 1.0,
                      consolidate: bool = True, n_trucks: int | None = None,
                      must_include: list[str] | None = None) -> dict:
    wmap = {o.id: o.weight for o in sc.orders}
    trucks = list(sc.trucks)
    if n_trucks is not None:
        trucks = rng.sample(trucks, min(n_trucks, len(trucks)))
    chosen = [o for o in sc.orders if rng.random() < frac]
    if must_include:
        ids = {o.id for o in chosen}
        chosen += [sc.order_by_id[i] for i in must_include if i not in ids]
    rng.shuffle(chosen)
    routes = {t.id: [] for t in trucks}
    for o in chosen:
        cands = [t for t in trucks if compatible(sc, o, t)]
        if not cands:
            continue
        t = rng.choice(cands)
        routes[t.id] = _insert(rng, routes[t.id], o, t.capacity, wmap, consolidate)
    keys = list(routes)
    rng.shuffle(keys)
    return {k: [{"action": a, "order": oid} for a, oid in routes[k]] for k in keys}


def mutate_invalid(sc: Scenario, plan: dict, rng: random.Random, n: int = 3) -> dict:
    """Apply n random rule-breaking mutations to a copy of plan."""
    p = {k: [dict(s) for s in v] for k, v in plan.items()}
    tids = [t.id for t in sc.trucks]
    oids = [o.id for o in sc.orders]
    for _ in range(n):
        k = rng.choice(list(p)) if p else rng.choice(tids)
        r = p.setdefault(k, [])
        m = rng.randrange(11)
        pos = rng.randint(0, len(r))
        if m >= 9:      # order of a type this truck cannot carry, sometimes messed up
            t = sc.truck_by_id.get(k)
            bad = [o for o in sc.orders if t and o.required_type and o.required_type != t.type]
            if bad:
                o = rng.choice(bad)
                seq = [{"action": "pickup", "order": o.id}, {"action": "delivery", "order": o.id}]
                if m == 10:
                    seq = rng.sample(seq + [dict(rng.choice(seq))], 3)
                r[pos:pos] = seq
            continue
        if m == 0:
            r.insert(pos, {"action": "pickup", "order": "O999"})
        elif m == 1:
            r.insert(pos, {"action": rng.choice(["drop", "Pickup", "DELIVERY"]),
                           "order": rng.choice(oids)})
        elif m == 2 and r:
            r.insert(pos, dict(rng.choice(r)))                 # duplicate a stop
        elif m == 3 and r:
            i = rng.randrange(len(r))
            r.insert(rng.randint(0, i), r.pop(i))              # move a stop earlier
        elif m == 4:
            r.insert(pos, {"action": "pickup", "order": rng.choice(oids)})   # maybe no delivery
        elif m == 5:
            o = rng.choice(sc.orders)
            r[pos:pos] = [{"action": "pickup", "order": o.id}, {"action": "delivery", "order": o.id}]
        elif m == 6:
            heavy = sorted(sc.orders, key=lambda o: -o.weight)[:4]
            for o in heavy:
                r.insert(0, {"action": "pickup", "order": o.id})
            for o in heavy:
                r.append({"action": "delivery", "order": o.id})
        elif m == 7:
            p["T99"] = [{"action": "pickup", "order": rng.choice(oids)}]
        elif m == 8 and r:
            i = rng.randrange(len(r))
            r.pop(i)
    return p
