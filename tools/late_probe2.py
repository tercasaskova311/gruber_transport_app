import json, random, collections
from gruber import loader, plangen, simulator
from tools.late_probe import lates

def search(sid, tries=150000, seed=3):
    sc = loader.load(sid); rng = random.Random(seed); out = []; hist = collections.Counter()
    both = [o for o in sc.orders if o.pw and o.dw]
    for _ in range(tries):
        o = rng.choice(both)
        t = rng.choice([t for t in sc.trucks if plangen.compatible(sc, o, t)])
        others = [x for x in sc.orders if x.id != o.id and plangen.compatible(sc, x, t) and not (x.pw or x.dw)]
        group = rng.sample(others, rng.randint(1, 4)) + [o]
        route = []
        wmap = {x.id: x.weight for x in sc.orders}
        for x in group:
            route = plangen._insert(rng, route, x, t.capacity, wmap, True)
        p = {t.id: [{"action": a, "order": i} for a, i in route]}
        r = lates(sc, p, o.id)
        if not r: continue
        hist[(r[0] > 0, r[1] > 0)] += 1
        if 0 < r[0] <= 60 and 0 < r[1] <= 60 and r[0] != r[1]:
            out.append({"order": o.id, "late_pickup": r[0], "late_delivery": r[1], "plan": p})
            if len(out) >= 3: break
    return out, hist

if __name__ == "__main__":
    res = {}
    for sid in ["scenario_middle", "scenario_big"]:
        r, h = search(sid); res[sid] = r
        print(sid, [(x["order"], x["late_pickup"], x["late_delivery"]) for x in r], dict(h))
    json.dump(res, open("data/parity/late_both_probes.json", "w"), indent=1)
