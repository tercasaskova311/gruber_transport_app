"""Write a small FAKE API dataset to tests/fixture/ (two scenarios, two time-window styles).

    python tests/make_fixture.py [--seed 1]
Scenario 1: snake_case keys, windows as {"from": min, "to": min}.
Scenario 2: camelCase keys, windows as a list with ISO timestamps.
"""
import argparse, json, math, random
from pathlib import Path

OUT = Path(__file__).parent / "fixture"


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)) * 1.25, 1)


def build(sid, rnd, n_c, n_t, n_o, style):
    cities = [{"id": f"C{i:03d}", "name": f"City{i}", "country": rnd.choice(["IT", "AT", "DE"]),
               "latitude": round(rnd.uniform(45.5, 48.5), 4), "longitude": round(rnd.uniform(10, 13.5), 4)}
              for i in range(1, n_c + 1)]
    ids = [c["id"] for c in cities]
    lines = ["city_id," + ",".join(ids)]
    for a in cities:
        lines.append(a["id"] + "," + ",".join(str(0 if a is b else km(a, b)) for b in cities))
    types = ["standard", "standard", "refrigerated", "hazmat"]
    trucks = [{"id": f"T{i:02d}", "start_city": rnd.choice(ids), "capacity_kg": rnd.choice([8000, 12000, 24000]),
               "type": types[i % 4], "cost_per_km": round(rnd.uniform(0.9, 1.6), 2),
               "co2_per_km": round(rnd.uniform(0.6, 1.1), 2)} for i in range(n_t)]
    orders = []
    for i in range(n_o):
        p, d = rnd.sample(ids, 2)
        req = rnd.choice([None, None, None, "refrigerated", "hazmat"])
        o = {"id": f"O{i:03d}", "pickup_city": p, "delivery_city": d,
             "weight_kg": rnd.choice([500, 2000, 6000, 15000, 30000 if i == 0 else 9000]),
             "required_truck_type": req}
        has_p, has_d = rnd.random() < 0.3, rnd.random() < 0.4
        value = (1.5 if req else 1.0) + (0.5 if (has_p or has_d) else 0)
        if style == "snake":
            o["value"] = value
            if has_p:
                a = rnd.randrange(0, 600); o["pickup_time_window"] = {"from": a, "to": a + 180}
            if has_d:
                a = rnd.randrange(240, 1200); o["delivery_time_window"] = {"from": a, "to": a + 240}
        else:
            o = {"Id": o["id"], "pickupCity": p, "deliveryCity": d, "weightKg": o["weight_kg"],
                 "requiredTruckType": req, "Value": value, "timeWindows": []}
            def iso(m):
                h, mi = divmod(360 + m, 60)
                return f"2026-11-{14 + h // 24}T{h % 24:02d}:{mi:02d}:00"
            if has_p:
                a = rnd.randrange(0, 600); o["timeWindows"].append({"type": "Pickup", "start": iso(a), "end": iso(a + 180)})
            if has_d:
                a = rnd.randrange(240, 1200); o["timeWindows"].append({"type": "Delivery", "start": iso(a), "end": iso(a + 240)})
        orders.append(o)
    if style == "camel":
        trucks = [{"Id": t["id"], "StartCity": t["start_city"], "CapacityKg": t["capacity_kg"], "Type": t["type"],
                   "CostPerKm": t["cost_per_km"], "Co2PerKm": t["co2_per_km"]} for t in trucks]
    meta = {"id": sid, "name": f"Fake scenario {sid}", "cities_count": n_c, "trucks_count": n_t, "orders_count": n_o}
    return meta, cities, trucks, orders, "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--seed", type=int, default=1); a = ap.parse_args()
    rnd = random.Random(a.seed)
    metas = []
    for sid, (nc, nt, no, style) in {1: (8, 5, 20, "snake"), 2: (12, 7, 40, "camel")}.items():
        meta, cities, trucks, orders, csv = build(sid, rnd, nc, nt, no, style)
        d = OUT / str(sid); d.mkdir(parents=True, exist_ok=True)
        (d / "Cities.json").write_text(json.dumps(cities))
        (d / "Trucks.json").write_text(json.dumps(trucks))
        (d / "Orders.json").write_text(json.dumps(orders))
        (d / "DistanceMatrix.csv").write_text(csv)
        metas.append(meta)
    (OUT / "Scenarios.json").write_text(json.dumps(metas))
    print(f"fixture written to {OUT} (seed {a.seed})")


if __name__ == "__main__":
    main()
