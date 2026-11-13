"""
make_fake_scenario.py — offline test data with the same shape as the official API.

Use it to develop the solver before/without API access. Real scenarios come from fetch.py.

    python make_fake_scenario.py --preset competitive --out data/fake_competitive
"""
from __future__ import annotations

import argparse
import sys
import json
import math
import random
from pathlib import Path

CITIES = [
    ("Belgrade", "RS", 44.79, 20.45), ("Vienna", "AT", 48.21, 16.37), ("Munich", "DE", 48.14, 11.58),
    ("Milan", "IT", 45.46, 9.19), ("Bolzano", "IT", 46.50, 11.35), ("Verona", "IT", 45.44, 10.99),
    ("Innsbruck", "AT", 47.27, 11.40), ("Zurich", "CH", 47.38, 8.54), ("Lyon", "FR", 45.76, 4.84),
    ("Paris", "FR", 48.86, 2.35), ("Brussels", "BE", 50.85, 4.35), ("Amsterdam", "NL", 52.37, 4.90),
    ("Rotterdam", "NL", 51.92, 4.48), ("Hamburg", "DE", 53.55, 9.99), ("Berlin", "DE", 52.52, 13.40),
    ("Frankfurt", "DE", 50.11, 8.68), ("Cologne", "DE", 50.94, 6.96), ("Stuttgart", "DE", 48.78, 9.18),
    ("Prague", "CZ", 50.08, 14.44), ("Warsaw", "PL", 52.23, 21.01), ("Krakow", "PL", 50.06, 19.94),
    ("Budapest", "HU", 47.50, 19.04), ("Bratislava", "SK", 48.15, 17.11), ("Ljubljana", "SI", 46.06, 14.51),
    ("Zagreb", "HR", 45.81, 15.98), ("Bologna", "IT", 44.49, 11.34), ("Florence", "IT", 43.77, 11.26),
    ("Rome", "IT", 41.90, 12.50), ("Naples", "IT", 40.85, 14.27), ("Turin", "IT", 45.07, 7.69),
    ("Genoa", "IT", 44.41, 8.93), ("Marseille", "FR", 43.30, 5.37), ("Barcelona", "ES", 41.39, 2.17),
    ("Madrid", "ES", 40.42, -3.70), ("Valencia", "ES", 39.47, -0.38), ("Lisbon", "PT", 38.72, -9.14),
    ("Bordeaux", "FR", 44.84, -0.58), ("Strasbourg", "FR", 48.57, 7.75), ("Copenhagen", "DK", 55.68, 12.57),
    ("Gothenburg", "SE", 57.71, 11.97), ("Bucharest", "RO", 44.43, 26.10), ("Sofia", "BG", 42.70, 23.32),
    ("Timisoara", "RO", 45.76, 21.23), ("Linz", "AT", 48.31, 14.29), ("Graz", "AT", 47.07, 15.44),
    ("Trento", "IT", 46.07, 11.12), ("Venice", "IT", 45.44, 12.32), ("Nuremberg", "DE", 49.45, 11.08),
]
PRESETS = {  # cities, trucks, orders, region_only, time_window_share
    "small": (10, 4, 20, True, 0.0), "middle": (20, 8, 50, True, 0.10),
    "big": (30, 15, 120, False, 0.20), "competitive": (45, 25, 200, False, 0.30),
}


def haversine(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (a[2], a[3], b[2], b[3]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main():
    try:
        sys.stdout.reconfigure(errors="replace")   # never crash on a console that lacks a symbol
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="small", choices=PRESETS)
    ap.add_argument("--out", default=None, help="default: data/fake_<preset>")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    n_c, n_t, n_o, region, tw_share = PRESETS[args.preset]

    pool = CITIES[:]
    if region:  # one region: cities closest to Bolzano
        pool.sort(key=lambda c: haversine(c, CITIES[4]))
        pool = pool[:n_c]
    else:
        pool = rng.sample(pool, n_c)
    cities = [{"id": f"C{i + 1:03d}", "name": c[0], "country": c[1], "latitude": c[2], "longitude": c[3]}
              for i, c in enumerate(pool)]
    ids = [c["id"] for c in cities]
    dm = {ids[i]: {ids[j]: round(haversine(pool[i], pool[j]) * 1.3) for j in range(n_c)} for i in range(n_c)}

    types = ["standard"] * n_t
    for i in rng.sample(range(n_t), max(1, n_t // 5)):
        types[i] = "refrigerated"
    for i in rng.sample([i for i in range(n_t) if types[i] == "standard"], max(1, n_t // 8)):
        types[i] = "hazmat"
    trucks = [{"id": f"T{i + 1:02d}", "start_city": rng.choice(ids),
               "capacity_kg": rng.choice([8000, 12000, 18000, 24000]), "type": types[i],
               "cost_per_km": round(rng.uniform(0.9, 1.6), 2), "co2_per_km": round(rng.uniform(0.6, 1.1), 2)}
              for i in range(n_t)]

    # import the real evaluator to make time windows reachable (spec guarantee)
    sys.path.insert(0, str(Path(__file__).parent))
    from evaluator import simulate_truck
    from instance import Instance, Order, Truck, precompute

    orders = []
    for i in range(n_o):
        p, d = rng.sample(ids, 2)
        r = rng.random()
        req = "refrigerated" if r < 0.15 else ("hazmat" if r < 0.22 else None)
        orders.append({"id": f"O{i + 1:03d}", "pickup_city": p, "delivery_city": d,
                       "weight_kg": rng.choice([800, 1500, 2500, 3200, 4500, 6000, 8000]),
                       "required_truck_type": req})

    # temporary instance to compute "alone" arrival times
    cidx = {c: i for i, c in enumerate(ids)}
    D = [[float(dm[a][b]) for b in ids] for a in ids]
    T = [Truck(i, t["id"], cidx[t["start_city"]], t["capacity_kg"], t["type"], t["cost_per_km"], t["co2_per_km"])
         for i, t in enumerate(trucks)]
    for i in rng.sample(range(n_o), int(round(tw_share * n_o))):
        o = orders[i]
        comp = [t for t in T if (o["required_truck_type"] in (None, t.type)) and o["weight_kg"] <= t.capacity]
        if not comp:
            continue
        near = min(comp, key=lambda t: D[t.start][cidx[o["pickup_city"]]])
        tmp = Instance(ids, ids, [0] * n_c, [0] * n_c, D, T,
                       [Order(0, o["id"], cidx[o["pickup_city"]], cidx[o["delivery_city"]], o["weight_kg"],
                              o["required_truck_type"], 1.0)])
        precompute(tmp)
        r = simulate_truck(tmp, near.idx, [(True, 0), (False, 0)])
        arrive_delivery = r.finish_min - 30
        lo = max(0, arrive_delivery - rng.randint(60, 300))
        hi = arrive_delivery + rng.randint(0, 180)
        o["time_window"] = {"from": int(lo), "to": int(hi), "applies_to": "delivery"}

    for o in orders:
        base = 1.5 if o["required_truck_type"] in ("refrigerated", "hazmat") else 1.0
        o["value"] = base + (0.5 if "time_window" in o else 0.0)

    out = Path(args.out or f"data/fake_{args.preset}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "cities.json").write_text(json.dumps(cities, indent=1), encoding="utf-8")
    (out / "trucks.json").write_text(json.dumps(trucks, indent=1), encoding="utf-8")
    (out / "orders.json").write_text(json.dumps(orders, indent=1), encoding="utf-8")
    (out / "distance_matrix.json").write_text(json.dumps(dm), encoding="utf-8")
    print(f"Wrote {args.preset}: {n_c} cities, {n_t} trucks, {n_o} orders → {out}")


if __name__ == "__main__":
    main()
