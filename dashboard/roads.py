"""Real road shapes for the map, so a leg is drawn along the motorway instead of as a curve.

Shapes come from the public OSRM demo router (OpenStreetMap roads, no API key) and are saved in
data/road_shapes_detail.json, so the dashboard never calls the internet while it runs (works offline
at the pitch). Only the drawing changes: km, cost and the score still come from the distance matrix.

We ask OSRM for the FULL road geometry and store it simplified to ~200 m, so the line stays on
the motorway even zoomed in to one region. The map simplifies further when zoomed out.
data/road_shapes.json is the older, coarse version (~40 points per leg): only a fallback.

Fill the file (about 1 request per second, the demo server's limit; new legs only):
    python3 dashboard/roads.py scenario_competitive
    python3 dashboard/roads.py            # every scenario that has plans in the DB
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA / "road_shapes_detail.json"        # full road geometry, simplified to ~200 m
OLD_CACHE = DATA / "road_shapes.json"           # coarse shapes from before: fallback only
OSRM = "https://router.project-osrm.org/route/v1/driving/{};{}?overview=full&geometries=geojson"
STORE_TOLERANCE = 0.002                          # degrees, ~200 m: invisible at any zoom we use

_shapes = None
_stamp = None                                    # file times when _shapes was read


def _key(a, b):
    """Same key for A->B and B->A. a, b = (lat, lon)."""
    pa, pb = (f"{a[0]:.4f},{a[1]:.4f}", f"{b[0]:.4f},{b[1]:.4f}")
    return (pa + "|" + pb, False) if pa <= pb else (pb + "|" + pa, True)


def _read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def _load():
    """Detailed shapes, falling back to the old coarse ones for legs not upgraded yet.
    Re-read when a file changed on disk (e.g. roads.py was run in a terminal while the
    dashboard was open), otherwise new roads only showed up after a restart."""
    global _shapes, _stamp
    stamp = tuple(p.stat().st_mtime if p.exists() else 0 for p in (OLD_CACHE, CACHE))
    if _shapes is None or stamp != _stamp:
        _smooth.clear()
        _shapes, _stamp = {**_read(OLD_CACHE), **_read(CACHE)}, stamp
    return _shapes


def _simplify(points, tolerance):
    """Douglas-Peucker: keep only the points that change the line's shape by more than `tolerance`
    degrees (0.01 ≈ 1 km). Iterative, because full road geometry has thousands of points."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        (y1, x1), (y2, x2) = points[i], points[j]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-9
        far, far_k = 0.0, None
        for k in range(i + 1, j):
            y, x = points[k]
            d = abs(dy * (x - x1) - dx * (y - y1)) / norm
            if d > far:
                far, far_k = d, k
        if far_k is not None and far > tolerance:
            keep[far_k] = True
            stack += [(i, far_k), (far_k, j)]
    return [p for p, k in zip(points, keep) if k]


_smooth = {}


def reset():
    """Forget what is in memory, so the next shape() re-reads the file (after fill())."""
    global _shapes
    _shapes = None
    _smooth.clear()


def shape(a, b, tolerance=0.01):
    """[[lat, lon], ...] following the road from a to b (smoothed), or None if we don't have it.
    Starts and ends exactly on the city dots."""
    key, flipped = _key(a, b)
    shapes = _load()                                # first: it clears _smooth if the file changed
    if (key, tolerance) not in _smooth:
        points = shapes.get(key)
        _smooth[key, tolerance] = _simplify(points, tolerance) if points else None
    points = _smooth[key, tolerance]
    if not points:
        return None
    points = points[::-1] if flipped else points
    return [list(a)] + points[1:-1] + [list(b)]


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
    full = [[lat, lon] for lon, lat in body["routes"][0]["geometry"]["coordinates"]]
    return [[round(lat, 4), round(lon, 4)] for lat, lon in _simplify(full, STORE_TOLERANCE)]


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


def fill(scenarios=None, max_new=None):
    """Fetch shapes for legs not in the detailed cache. With max_new, do nothing when more than
    that many are missing (the dashboard's Refresh button must not hang for minutes);
    then the count is returned negative."""
    import duckdb
    db = CACHE.parent / "hackathon.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        if not scenarios:
            scenarios = [r[0] for r in con.execute("SELECT DISTINCT scenario_id FROM results.runs ORDER BY 1").fetchall()]
        pairs = set()
        for sc in scenarios:
            pairs |= _city_pairs(con, sc)
    shapes = _read(CACHE)
    todo = {_key(a, b)[0]: (a, b) for a, b in pairs if _key(a, b)[0] not in shapes}
    if max_new is not None and len(todo) > max_new:
        return -len(todo)
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
    reset()
    return sum(1 for k in todo if k in shapes)


if __name__ == "__main__":
    fill(sys.argv[1:])
