"""Find small plans whose local result depends on an unresolved SEM switch."""
import json, random, sys
from gruber import loader, simulator, plangen

def result(sc, p):
    return json.dumps(simulator.api_round(simulator.score(sc, p)), sort_keys=True)

def differs(sc, p, key, alt):
    a = result(sc, p); old = simulator.SEM[key]; simulator.SEM[key] = alt
    b = result(sc, p); simulator.SEM[key] = old
    return a != b

def search(sid, key, alt, k=2, tries=20000, seed=0):
    sc = loader.load(sid); rng = random.Random(seed); out = []
    tw = [o for o in sc.orders if o.pw or o.dw]
    both = [o for o in sc.orders if o.pw and o.dw]
    for _ in range(tries):
        if len(out) >= k: break
        o = rng.choice(both if key == "order_late" and both else tw)
        ts = [t for t in sc.trucks if plangen.compatible(sc, o, t)]
        if not ts: continue
        t = rng.choice(ts)
        others = [x for x in sc.orders if x.id != o.id and plangen.compatible(sc, x, t)]
        pre = rng.sample(others, min(len(others), rng.randint(0, 4)))
        stops = []
        for x in pre: stops += [{"action": "pickup", "order": x.id}, {"action": "delivery", "order": x.id}]
        stops += [{"action": "pickup", "order": o.id}, {"action": "delivery", "order": o.id}]
        if rng.random() < .5 and pre:   # something after, so a post-wait drive happens
            x = rng.choice([y for y in others if y not in pre] or pre)
            if x not in pre: stops += [{"action": "pickup", "order": x.id}, {"action": "delivery", "order": x.id}]
        p = {t.id: stops}
        if simulator.simulate(sc, p)["validation"]["is_valid"] and differs(sc, p, key, alt):
            out.append(p)
    return out

if __name__ == "__main__":
    for sid in ["scenario_middle", "scenario_big"]:
        for key, alt in [("idle_counts_as_rest", False), ("order_late", "sum")]:
            ps = search(sid, key, alt)
            print(sid, key, len(ps), [sum(len(v) for v in p.values()) for p in ps])


def search2(sid, key, alt, k=2, tries=60000, seed=1):
    """Targeted: [prefix orders] + TW order + [long post orders]."""
    sc = loader.load(sid); rng = random.Random(seed); out = []
    cand = [o for o in sc.orders if (o.pw and o.dw)] if key == "order_late" else \
           sorted([o for o in sc.orders if o.pw or o.dw], key=lambda o: -max((o.pw or (0, 0))[0], (o.dw or (0, 0))[0]))[:8]
    for _ in range(tries):
        if len(out) >= k or not cand: break
        o = rng.choice(cand)
        ts = [t for t in sc.trucks if plangen.compatible(sc, o, t)]
        if not ts: continue
        t = rng.choice(ts)
        others = [x for x in sc.orders if x.id != o.id and plangen.compatible(sc, x, t) and not (x.pw or x.dw)]
        pre = rng.sample(others, rng.randint(0, 6 if key == "order_late" else 2))
        post = rng.sample([x for x in others if x not in pre], rng.randint(0, 3)) if key != "order_late" else []
        stops = []
        for x in pre: stops += [{"action": "pickup", "order": x.id}, {"action": "delivery", "order": x.id}]
        stops += [{"action": "pickup", "order": o.id}, {"action": "delivery", "order": o.id}]
        for x in post: stops += [{"action": "pickup", "order": x.id}, {"action": "delivery", "order": x.id}]
        p = {t.id: stops}
        if simulator.simulate(sc, p)["validation"]["is_valid"] and differs(sc, p, key, alt):
            out.append(p)
    return out
