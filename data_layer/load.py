"""load.py : hand one scenario to the solver as numpy arrays.

    import duckdb, load
    con = load.connect()                     # read-only, retries if fetch.py is writing
    sc = load.load_scenario(con, "1")
    sc.D_km[sc.order_pickup[0], sc.order_delivery[0]]
    sc.compat[o, t]                          # True if truck t may carry order o
    load.save_run(con_rw, sc, algo="greedy", plan=..., stops=[...], local_score=123.4)

Everything is indexed 0..N-1 exactly like prepare.sql (city_idx, truck idx, order_idx).
Missing time-window bounds are 0 (from) and INF (to), so no NULL handling in the solver.
"""
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import duckdb
import numpy as np

import config as C

INF = np.iinfo(np.int32).max // 2   # "no deadline", still safe to add to


def connect(read_only=True, tries=30):
    """DuckDB lets only one process write. If fetch.py is mid-write, wait and retry."""
    for i in range(tries):
        try:
            return duckdb.connect(str(C.DB_PATH), read_only=read_only)
        except duckdb.IOException:
            if i == tries - 1:
                raise
            time.sleep(1)


@dataclass
class Scenario:
    scenario_id: str
    snapshot_id: str
    # cities
    city_ids: list
    city_index: dict              # city_id -> idx
    D_km: np.ndarray              # (N, N) float
    D_min: np.ndarray             # (N, N) int, drive minutes
    # trucks
    truck_ids: list
    truck_index: dict
    truck_start: np.ndarray       # city idx
    truck_cap: np.ndarray
    truck_type: np.ndarray        # str
    truck_cost_km: np.ndarray
    truck_co2_km: np.ndarray
    # orders
    order_ids: list
    order_index: dict
    order_pickup: np.ndarray      # city idx
    order_delivery: np.ndarray    # city idx
    order_weight: np.ndarray
    order_req_type: np.ndarray    # str or None
    order_value: np.ndarray
    pickup_tw: np.ndarray         # (M, 2) int  [from, to]
    delivery_tw: np.ndarray       # (M, 2) int
    order_priority: np.ndarray    # order idx sorted, most urgent first
    compat: np.ndarray            # (M, T) bool
    stats: dict = field(default_factory=dict)
    service_min: int = C.SERVICE_MIN

    @property
    def n_cities(self): return len(self.city_ids)
    @property
    def n_trucks(self): return len(self.truck_ids)
    @property
    def n_orders(self): return len(self.order_ids)


def _rows(con, sql, sid):
    cur = con.execute(sql, [sid])
    cols = [d[0] for d in cur.description]
    return {c: list(v) for c, v in zip(cols, zip(*cur.fetchall()))} if cols else {}


def list_scenarios(con):
    return [r[0] for r in con.execute("SELECT scenario_id FROM scenario_stats ORDER BY scenario_id").fetchall()]


def load_scenario(con, scenario_id):
    sid = str(scenario_id)
    snap = con.execute("SELECT snapshot_id FROM cur_snapshots WHERE scenario_id = ?", [sid]).fetchall()
    if not snap:
        raise KeyError(f"scenario {sid} not in database; run fetch.py")

    cities = _rows(con, "SELECT idx, city_id FROM city_idx WHERE scenario_id = ? ORDER BY idx", sid)
    n = len(cities["idx"])
    D_km = np.full((n, n), np.nan)
    D_min = np.full((n, n), INF, dtype=np.int32)
    legs = con.execute("SELECT from_idx, to_idx, km, drive_min FROM legs WHERE scenario_id = ?", [sid]).fetchnumpy()
    D_km[legs["from_idx"], legs["to_idx"]] = legs["km"]
    D_min[legs["from_idx"], legs["to_idx"]] = legs["drive_min"]

    t = _rows(con, """SELECT idx, truck_id, start_idx, capacity_kg, type, cost_per_km, co2_per_km
                      FROM truck_features WHERE scenario_id = ? ORDER BY idx""", sid)
    o = _rows(con, """SELECT order_idx, order_id, pickup_idx, delivery_idx, weight_kg, required_truck_type, value,
                             pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to, priority_rank
                      FROM order_features WHERE scenario_id = ? ORDER BY order_idx""", sid)
    m, k = len(o.get("order_idx", [])), len(t.get("idx", []))

    def tw(lo, hi):
        return np.array([[0 if a is None else a, INF if b is None else b]
                         for a, b in zip(o[lo], o[hi])], dtype=np.int32).reshape(m, 2)

    compat = np.zeros((m, k), dtype=bool)
    pairs = con.execute("SELECT order_idx, truck_idx FROM order_truck_compat WHERE scenario_id = ?", [sid]).fetchnumpy()
    compat[pairs["order_idx"], pairs["truck_idx"]] = True

    stats_cur = con.execute("SELECT * FROM scenario_stats WHERE scenario_id = ?", [sid])
    stats_desc = [d[0] for d in stats_cur.description]
    stats = dict(zip(stats_desc, stats_cur.fetchall()[0]))

    return Scenario(
        scenario_id=sid, snapshot_id=snap[0][0],
        city_ids=cities["city_id"], city_index={c: i for i, c in enumerate(cities["city_id"])},
        D_km=D_km, D_min=D_min,
        truck_ids=t.get("truck_id", []), truck_index={c: i for i, c in enumerate(t.get("truck_id", []))},
        truck_start=np.array(t.get("start_idx", []), dtype=np.int32),
        truck_cap=np.array(t.get("capacity_kg", []), dtype=float),
        truck_type=np.array(t.get("type", []), dtype=object),
        truck_cost_km=np.array(t.get("cost_per_km", []), dtype=float),
        truck_co2_km=np.array(t.get("co2_per_km", []), dtype=float),
        order_ids=o.get("order_id", []), order_index={c: i for i, c in enumerate(o.get("order_id", []))},
        order_pickup=np.array(o.get("pickup_idx", []), dtype=np.int32),
        order_delivery=np.array(o.get("delivery_idx", []), dtype=np.int32),
        order_weight=np.array(o.get("weight_kg", []), dtype=float),
        order_req_type=np.array(o.get("required_truck_type", []), dtype=object),
        order_value=np.array([np.nan if v is None else v for v in o.get("value", [])], dtype=float),
        pickup_tw=tw("pickup_tw_from", "pickup_tw_to") if m else np.zeros((0, 2), np.int32),
        delivery_tw=tw("delivery_tw_from", "delivery_tw_to") if m else np.zeros((0, 2), np.int32),
        order_priority=np.argsort(np.array(o.get("priority_rank", []))).astype(np.int32),
        compat=compat, stats=stats,
    )


def save_run(con, sc, algo, plan, stops=(), params=None, local_score=None, api_score=None,
             score_parts=None, n_orders_served=None, violations=None):
    """Store one solver result. `con` must be writable (load.connect(read_only=False)).

    stops: iterable of dicts with keys truck_id, seq, action, order_id, city_id,
           arrival_min, departure_min, load_kg, late_min (missing keys -> NULL).
    score_parts: dict with any of value, cost, co2, km.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    sp = score_parts or {}
    con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        run_id, sc.scenario_id, sc.snapshot_id, datetime.now(timezone.utc).replace(tzinfo=None), algo,
        json.dumps(params or {}), local_score, api_score,
        sp.get("value"), sp.get("cost"), sp.get("co2"), sp.get("km"),
        n_orders_served, violations, json.dumps(plan)])
    keys = ("truck_id", "seq", "action", "order_id", "city_id", "arrival_min", "departure_min", "load_kg", "late_min")
    rows = [(run_id,) + tuple(s.get(k) for k in keys) for s in stops]
    if rows:
        con.executemany("INSERT INTO run_stops VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return run_id


if __name__ == "__main__":
    with connect() as con:
        for sid in list_scenarios(con):
            sc = load_scenario(con, sid)
            print(f"scenario {sid} (snapshot {sc.snapshot_id}): {sc.n_cities} cities, "
                  f"{sc.n_trucks} trucks, {sc.n_orders} orders, compat pairs={int(sc.compat.sum())}")
