"""
instance.py — load a scenario into fast, index-based Python structures.

Expected folder layout (what fetch.py should save, one JSON per API endpoint):
    <scenario_dir>/cities.json            GET /Scenarios/{id}/Cities
    <scenario_dir>/trucks.json            GET /Scenarios/{id}/Trucks
    <scenario_dir>/orders.json            GET /Scenarios/{id}/Orders
    <scenario_dir>/distance_matrix.json   GET /Scenarios/{id}/DistanceMatrix

Everything is converted to integer indices so the solver can use plain lists
(much faster than dict lookups or numpy scalars inside tight loops).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------
# Order value rules (spec §9.1) — used only if the API does not send "value".
# --------------------------------------------------------------------------
BASE_VALUE = {None: 1.0, "standard": 1.0, "refrigerated": 1.5, "hazmat": 1.5}
TIME_WINDOW_BONUS = 0.5

# A generic "time_window" field (no pickup/delivery prefix) is applied here.
# ⚠ ASSUMPTION — check the real JSON on day 1 and adjust.
GENERIC_WINDOW_APPLIES_TO = "delivery"


@dataclass
class Truck:
    idx: int
    id: str
    start: int          # city index
    capacity: float
    type: str
    cost_per_km: float
    co2_per_km: float


@dataclass
class Order:
    idx: int
    id: str
    p: int              # pickup city index
    d: int              # delivery city index
    weight: float
    required_type: Optional[str]
    value: float
    ptw: Optional[tuple[float, float]] = None   # pickup window (from, to) in minutes
    dtw: Optional[tuple[float, float]] = None   # delivery window (from, to) in minutes


@dataclass
class Instance:
    city_ids: list[str]
    city_names: list[str]
    lat: list[float]
    lon: list[float]
    D: list[list[float]]                         # km, D[i][j]
    trucks: list[Truck]
    orders: list[Order]
    # precomputed
    compatible: list[list[int]] = field(default_factory=list)   # order -> truck indices
    direct_km: list[float] = field(default_factory=list)
    value_total: float = 0.0
    direct_km_total: float = 0.0
    min_cost_per_km: float = 0.0
    min_co2_per_km: float = 0.0
    # where the data came from (set by load_from_db; empty for JSON folders)
    scenario_id: str = ""
    snapshot_id: str = ""

    @property
    def n_orders(self) -> int:
        return len(self.orders)


# --------------------------------------------------------------------------
def _parse_window(raw) -> Optional[tuple[float, float]]:
    """Accept {"from": a, "to": b} / {"start","end"} / {"earliest","latest"} / [a, b]."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        a, b = raw
    elif isinstance(raw, dict):
        a = next((raw[k] for k in ("from", "start", "earliest", "from_min") if k in raw), None)
        b = next((raw[k] for k in ("to", "end", "latest", "to_min") if k in raw), None)
        if a is None and b is None:
            return None
    else:
        raise ValueError(f"Unrecognised time-window format: {raw!r}")
    if not all(isinstance(x, (int, float)) or x is None for x in (a, b)):
        raise ValueError(
            f"Time window {raw!r} is not in minutes. Convert it in instance._parse_window "
            "(minute 0 = Day 1, 06:00)."
        )
    return (float(a) if a is not None else 0.0, float(b) if b is not None else float("inf"))


def _windows_of(o: dict) -> tuple[Optional[tuple], Optional[tuple]]:
    ptw = dtw = None
    for k in ("pickup_window", "pickup_time_window", "pickup_tw"):
        if o.get(k) is not None:
            ptw = _parse_window(o[k])
    for k in ("delivery_window", "delivery_time_window", "delivery_tw"):
        if o.get(k) is not None:
            dtw = _parse_window(o[k])
    if o.get("time_window") is not None:
        w = _parse_window(o["time_window"])
        target = (o["time_window"].get("applies_to") if isinstance(o["time_window"], dict) else None) \
            or GENERIC_WINDOW_APPLIES_TO
        if target == "pickup":
            ptw = w
        else:
            dtw = w
    return ptw, dtw


def load_instance(folder: str | Path) -> Instance:
    folder = Path(folder)
    cities = json.loads((folder / "cities.json").read_text(encoding="utf-8"))
    trucks_raw = json.loads((folder / "trucks.json").read_text(encoding="utf-8"))
    orders_raw = json.loads((folder / "orders.json").read_text(encoding="utf-8"))
    dm = json.loads((folder / "distance_matrix.json").read_text(encoding="utf-8"))

    city_ids = [c["id"] for c in cities]
    cidx = {cid: i for i, cid in enumerate(city_ids)}
    D = [[float(dm[a][b]) for b in city_ids] for a in city_ids]

    trucks = [
        Truck(i, t["id"], cidx[t["start_city"]], float(t["capacity_kg"]), t.get("type", "standard"),
              float(t["cost_per_km"]), float(t["co2_per_km"]))
        for i, t in enumerate(trucks_raw)
    ]

    orders = []
    for i, o in enumerate(orders_raw):
        ptw, dtw = _windows_of(o)
        req = o.get("required_truck_type")
        value = o.get("value")
        if value is None:
            value = BASE_VALUE.get(req, 1.0) + (TIME_WINDOW_BONUS if (ptw or dtw) else 0.0)
        orders.append(Order(i, o["id"], cidx[o["pickup_city"]], cidx[o["delivery_city"]],
                            float(o["weight_kg"]), req, float(value), ptw, dtw))

    inst = Instance(city_ids, [c.get("name", c["id"]) for c in cities],
                    [c.get("latitude", 0.0) for c in cities], [c.get("longitude", 0.0) for c in cities],
                    D, trucks, orders)
    precompute(inst)
    return inst


def list_db_scenarios() -> list[str]:
    """Every scenario in the DB's prep schema (data_layer.load.list_scenarios)."""
    import settings  # noqa: F401,PLC0415  (puts the repo root on sys.path)
    from data_layer import load as dl  # noqa: PLC0415

    con = dl.connect()
    try:
        return dl.list_scenarios(con)
    finally:
        con.close()


def load_from_db(scenario_id: str) -> Instance:
    """Build the same Instance as load_instance(), from data_layer's prep.* tables.

    Positions (city_pos, truck_pos, order_pos) become the solver's indices. Plans are written
    with ids, so the different order vs. the JSON files does not matter.
    The connection comes from data_layer.load.connect() (same DB file, read-only, waits if
    fetch.py is writing). Imported here so the JSON route keeps working without duckdb.
    """
    import settings  # noqa: F401,PLC0415  (puts the repo root on sys.path)
    from data_layer import load as dl  # noqa: PLC0415

    sid = str(scenario_id)
    con = dl.connect()
    try:
        def rows(sql):
            return con.execute(sql, [sid]).fetchall()

        snap = rows("SELECT snapshot_id FROM raw.cur_snapshots WHERE scenario_id = ?")
        if not snap:
            raise KeyError(f"{sid} is not in {settings.DB_PATH}; run data_layer/run_all.sh")

        cities = rows("""SELECT city_pos, city_id, name, latitude, longitude
                         FROM prep.city_index WHERE scenario_id = ? ORDER BY city_pos""")
        n = len(cities)
        D = [[0.0] * n for _ in range(n)]
        for a, b, km in rows("SELECT from_pos, to_pos, km FROM prep.city_distances WHERE scenario_id = ?"):
            D[a][b] = float(km)

        trucks = [Truck(pos, tid, start, float(cap), (typ or "standard").lower(), float(cost), float(co2))
                  for pos, tid, start, cap, typ, cost, co2 in rows(
                      """SELECT truck_pos, truck_id, start_pos, capacity_kg, type, cost_per_km, co2_per_km
                         FROM prep.truck_features WHERE scenario_id = ? ORDER BY truck_pos""")]

        def window(lo, hi):
            if lo is None and hi is None:
                return None
            return (float(lo) if lo is not None else 0.0, float(hi) if hi is not None else float("inf"))

        orders = []
        for (pos, oid, p, d, w, req, value, pf, pt, df, dt) in rows(
                """SELECT order_pos, order_id, pickup_pos, delivery_pos, weight_kg, required_truck_type,
                          value, pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to
                   FROM prep.order_features WHERE scenario_id = ? ORDER BY order_pos"""):
            req = req.lower() if req else None
            ptw, dtw = window(pf, pt), window(df, dt)
            if value is None:
                value = BASE_VALUE.get(req, 1.0) + (TIME_WINDOW_BONUS if (ptw or dtw) else 0.0)
            orders.append(Order(pos, oid, p, d, float(w), req, float(value), ptw, dtw))

        prep_options = rows("SELECT order_pos, truck_pos FROM prep.order_truck_options WHERE scenario_id = ?")
    finally:
        con.close()

    inst = Instance([c[1] for c in cities], [c[2] or c[1] for c in cities],
                    [c[3] or 0.0 for c in cities], [c[4] or 0.0 for c in cities],
                    D, trucks, orders, scenario_id=sid, snapshot_id=snap[0][0])
    precompute(inst)

    # prep.order_truck_options and precompute() apply the same type + capacity rule;
    # if they ever disagree, one of them changed and the solver would silently differ.
    from_prep = [set() for _ in orders]
    for o, k in prep_options:
        from_prep[o].add(k)
    bad = [orders[i].id for i in range(len(orders)) if from_prep[i] != set(inst.compatible[i])]
    if bad:
        raise ValueError(f"prep.order_truck_options disagrees with the solver for orders {bad[:5]}")
    return inst


def precompute(inst: Instance) -> None:
    inst.compatible = [
        [t.idx for t in inst.trucks
         if (o.required_type is None or t.type == o.required_type) and o.weight <= t.capacity]
        for o in inst.orders
    ]
    inst.direct_km = [inst.D[o.p][o.d] for o in inst.orders]
    inst.value_total = sum(o.value for o in inst.orders)
    inst.direct_km_total = sum(inst.direct_km)
    inst.min_cost_per_km = min(t.cost_per_km for t in inst.trucks)
    inst.min_co2_per_km = min(t.co2_per_km for t in inst.trucks)
