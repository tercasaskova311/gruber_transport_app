"""Compare local validation with the API's free Validate endpoint on random plans.

  python -m tools.validate_fuzz [n_per_scenario] [seed]
"""
import json
import random
import sys

from simulator import loader, simulator
from tools import plangen
from simulator.api import Client

SCEN = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"]


def key(v):
    return (v["rule"], v["truck"], v["order"] or None, v["message"])


def main(n=20, seed=0):
    c = Client()
    rng = random.Random(seed)
    bad = total = 0
    for sid in SCEN:
        sc = loader.load(sid)
        for i in range(n):
            p = plangen.random_valid_plan(sc, rng, frac=rng.choice([0.3, 0.7, 1.0]),
                                          consolidate=rng.random() < 0.7)
            if i % 4:
                p = plangen.mutate_invalid(sc, p, rng, n=rng.randint(1, 6))
            api = c.validate(sid, p)
            loc = simulator.simulate(sc, p)["validation"]
            a = [key(v) for v in api["violations"]]
            l = [key(v) for v in loc["violations"]]
            total += 1
            if a != l or api["is_valid"] != loc["is_valid"]:
                bad += 1
                print("MISMATCH", sid, i, flush=True)
                for x in a:
                    if x not in l: print("   only api:  ", x)
                for x in l:
                    if x not in a: print("   only local:", x)
                if sorted(a) == sorted(l): print("   (same set, different order)")
            else:
                print(f"ok {sid} {i}: {len(a)} violations", flush=True)
    print(f"{total - bad}/{total} plans: identical violation lists (rule, truck, order, message, order)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20, int(sys.argv[2]) if len(sys.argv) > 2 else 0)
