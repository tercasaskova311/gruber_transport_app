"""Real road shapes for the map, so a leg is drawn along the motorway instead of as a curve.

Shapes come from the public OSRM demo router (OpenStreetMap roads, no API key) and are saved in
data/road_shapes.json, so the dashboard never calls the internet while it runs (works offline
at the pitch). Only the drawing changes: km, cost and the score still come from the distance matrix.

Fill the file once per scenario (about 1 request per second, the demo server's limit):
    python3 dashboard/roads.py scenario_big
    python3 dashboard/roads.py            # every scenario that has plans in the DB
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "data" / "road_shapes.json"
OSRM = "https://router.project-osrm.org/route/v1/driving/{};{}?overview=simplified&geometries=geojson"

_shapes = None


def _key(a, b):
    """Same key for A->B and B->A. a, b = (lat, lon)."""
    pa, pb = (f"{a[0]:.4f},{a[1]:.4f}", f"{b[0]:.4f},{b[1]:.4f}")
    return (pa + "|" + pb, False) if pa <= pb else (pb + "|" + pa, True)


def _load():
    global _shapes
    if _shapes is None:
        _shapes = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    return _shapes


def shape(a, b):
    """[[lat, lon], ...] along the road from a to b, or None if we don't have it."""
    key, flipped = _key(a, b)
    points = _load().get(key)
    if not points:
        return None
    return points[::-1] if flipped else points


# ----------------------------------------------------------------------------------------
# Filling the cache
# ----------------------------------------------------------------------------------------
def _fetch(a, b):
    url = OSRM.format(f"{a[1]},{a[0]}", f"{b[1]},{b[0]}")
    req = urllib.request.Request(url, headers={"User-Agent": "hackathon-route-demo"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if body.get("code") != "Ok":
        return []                                   # no road (island, ferry only): the map draws a curve
    return [[round(lat, 5), round(lon, 5)] for lon, lat in body["routes"][0]["geometry"]["coordinates"]]


def _city_pairs(con, scenario, max_runs=40):
    """Every (city, city) leg driven in the scenario's best plans (the ones the dashboard lists)."""
    cities = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT raw_json->>'id', (raw_json->>'latitude')::DOUBLE, (raw_json->>'longitude')::DOUBLE "
        "FROM raw.cur_cities WHERE scenario_id = ?", [scenario]).fetchall()}
    orders = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT raw_json->>'id', raw_json->>'pickup_city', raw_json->>'delivery_city' "
        "FROM raw.cur_orders WHERE scenario_id = ?", [scenario]).fetchall()}
    starts = {r[0]: r[1] for r in con.execute(
        "SELECT raw_json->>'id', raw_json->>'start_city' FROM raw.cur_trucks WHERE scenario_id = ?",
        [scenario]).fetchall()}
    pairs = set()
    for (plan_json,) in con.execute(
            "SELECT plan_json FROM results.runs WHERE scenario_id = ? "
            "ORDER BY n_violations = 0 DESC, score DESC LIMIT ?", [scenario, max_runs]).fetchall():
        for tid, stops in json.loads(plan_json).items():
            here = starts.get(tid)
            for s in stops:
                o = orders.get(s.get("order"))
                if not o or here is None:
                    continue
                city = o[0] if s.get("action") == "pickup" else o[1]
                if city != here:
                    pairs.add((cities[here], cities[city]))
                here = city
    return pairs


def fill(scenarios=None):
    import duckdb
    db = CACHE.parent / "hackathon.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        if not scenarios:
            scenarios = [r[0] for r in con.execute("SELECT DISTINCT scenario_id FROM results.runs ORDER BY 1").fetchall()]
        pairs = set()
        for sc in scenarios:
            pairs |= _city_pairs(con, sc)
    shapes = _load()
    todo = {_key(a, b)[0]: (a, b) for a, b in pairs if _key(a, b)[0] not in shapes}
    print(f"{len(pairs)} legs in {', '.join(scenarios)}; {len(todo)} not cached yet")
    for i, (key, (a, b)) in enumerate(sorted(todo.items()), 1):
        if _key(a, b)[1]:
            a, b = b, a                             # store in key order
        try:
            shapes[key] = _fetch(a, b)
        except Exception as e:                      # keep going; a later run retries it
            print(f"  {key}: {e}")
            continue
        if i % 20 == 0 or i == len(todo):
            CACHE.write_text(json.dumps(shapes, separators=(",", ":")))
            print(f"  {i}/{len(todo)} saved")
        time.sleep(1.05)                            # OSRM demo server: max 1 request per second
    CACHE.write_text(json.dumps(shapes, separators=(",", ":")))


if __name__ == "__main__":
    fill(sys.argv[1:])
