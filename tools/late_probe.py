"""Search plans where one order is late (1..60 min) at BOTH pickup and delivery.
Such a plan tells max / sum / pickup-only / delivery-only lateness apart."""
import json, random, sys
from gruber import loader, simulator, plangen

def PD(x): return [{"action": "pickup", "order": x.id}, {"action": "delivery", "order": x.id}]

def lates(sc, p, oid):
    sim = simulator.simulate(sc, p)
    if not sim["validation"]["is_valid"]: return None
    s = [e for e in sim["metrics"]["trucks"][0]["schedule"] if e["order"] == oid]
    return s[0]["late_min"], s[1]["late_min"]

def search(sid, k=3, seed=0, pre_tries=3000):
    sc = loader.load(sid); rng = random.Random(seed); out = []
    for o in [o for o in sc.orders if o.pw and o.dw]:
        for t in [t for t in sc.trucks if plangen.compatible(sc, o, t)]:
            others = [x for x in sc.orders if x.id != o.id and plangen.compatible(sc, x, t) and not (x.pw or x.dw)]
            for _ in range(pre_tries):
                pre = rng.sample(others, rng.randint(1, 4))
                stops = [s for x in pre for s in PD(x)]
                r = lates(sc, {t.id: stops + PD(o)}, o.id)
                if not r or not (0 < r[0] <= 60): continue
                rest = [x for x in others if x not in pre]
                mids = [[x] for x in rest] + [rng.sample(rest, 2) for _ in range(300)]
                for mid in mids:
                    p = {t.id: stops + [PD(o)[0]] + [s for x in mid for s in PD(x)] + [PD(o)[1]]}
                    r2 = lates(sc, p, o.id)
                    if r2 and 0 < r2[1] <= 60 and r2[0] != r2[1]:
                        out.append({"order": o.id, "late_pickup": r2[0], "late_delivery": r2[1], "plan": p})
                        break
                if len(out) >= k or (out and out[-1]["order"] == o.id): break
            if len(out) >= k or (out and out[-1]["order"] == o.id): break
        if len(out) >= k: break
    return out

if __name__ == "__main__":
    res = {}
    for sid in ["scenario_middle", "scenario_big"]:
        r = search(sid); res[sid] = r
        print(sid, [(x["order"], x["late_pickup"], x["late_delivery"]) for x in r])
    json.dump(res, open("data/parity/late_both_probes.json", "w"), indent=1)
