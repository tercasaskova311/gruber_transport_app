"""load.py : hand one scenario to the solver as numpy arrays.

    import duckdb, load
    con = load.connect()                     # read-only, retries if fetch.py is writing
    sc = load.load_scenario(con, "1")
    sc.D_km[sc.order_pickup[0], sc.order_delivery[0]]
    sc.compat[o, t]                          # True if truck t may carry order o
    load.save_run(con_rw, sc, plan, api_response, algo="greedy", source="score")

Reads prep.* (+ raw.cur_snapshots), writes results.*.
Everything is indexed 0..N-1 exactly like prepare.sql (city_pos, truck_pos, order_pos).
Missing time-window bounds are 0 (from) and INF (to), so no NULL handling in the solver.
"""
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import duckdb
import numpy as np

try:
    from . import config as C
except ImportError:  # run as a script from database/ (python fetch.py)
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
    city_index: dict              # city_id -> position
    D_km: np.ndarray              # (N, N) float
    D_min: np.ndarray             # (N, N) int, drive minutes
    # trucks
    truck_ids: list
    truck_index: dict
    truck_start: np.ndarray       # city position
    truck_cap: np.ndarray
    truck_type: np.ndarray        # str
    truck_cost_km: np.ndarray
    truck_co2_km: np.ndarray
    # orders
    order_ids: list
    order_index: dict
    order_pickup: np.ndarray      # city position
    order_delivery: np.ndarray    # city position
    order_weight: np.ndarray
    order_req_type: np.ndarray    # str or None
    order_value: np.ndarray
    pickup_tw: np.ndarray         # (M, 2) int  [from, to]
    delivery_tw: np.ndarray       # (M, 2) int
    order_priority: np.ndarray    # order position sorted, most urgent first
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
    return [r[0] for r in con.execute("SELECT scenario_id FROM prep.scenario_summary ORDER BY scenario_id").fetchall()]


def load_scenario(con, scenario_id):
    sid = str(scenario_id)
    snap = con.execute("SELECT snapshot_id FROM raw.cur_snapshots WHERE scenario_id = ?", [sid]).fetchall()
    if not snap:
        raise KeyError(f"scenario {sid} not in database; run fetch.py")

    cities = _rows(con, "SELECT city_pos, city_id FROM prep.city_index WHERE scenario_id = ? ORDER BY city_pos", sid)
    n = len(cities["city_pos"])
    D_km = np.full((n, n), np.nan)
    D_min = np.full((n, n), INF, dtype=np.int32)
    city_distances = con.execute("SELECT from_pos, to_pos, km, drive_minutes FROM prep.city_distances WHERE scenario_id = ?", [sid]).fetchnumpy()
    D_km[city_distances["from_pos"], city_distances["to_pos"]] = city_distances["km"]
    D_min[city_distances["from_pos"], city_distances["to_pos"]] = city_distances["drive_minutes"]

    t = _rows(con, """SELECT truck_pos, truck_id, start_pos, capacity_kg, type, cost_per_km, co2_per_km
                      FROM prep.truck_features WHERE scenario_id = ? ORDER BY truck_pos""", sid)
    o = _rows(con, """SELECT order_pos, order_id, pickup_pos, delivery_pos, weight_kg, required_truck_type, value,
                             pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to, planning_order
                      FROM prep.order_features WHERE scenario_id = ? ORDER BY order_pos""", sid)
    m, k = len(o.get("order_pos", [])), len(t.get("truck_pos", []))

    def tw(lo, hi):
        return np.array([[0 if a is None else a, INF if b is None else b]
                         for a, b in zip(o[lo], o[hi])], dtype=np.int32).reshape(m, 2)

    compat = np.zeros((m, k), dtype=bool)
    pairs = con.execute("SELECT order_pos, truck_pos FROM prep.order_truck_options WHERE scenario_id = ?", [sid]).fetchnumpy()
    compat[pairs["order_pos"], pairs["truck_pos"]] = True

    stats_cur = con.execute("SELECT * FROM prep.scenario_summary WHERE scenario_id = ?", [sid])
    stats_desc = [d[0] for d in stats_cur.description]
    stats = dict(zip(stats_desc, stats_cur.fetchall()[0]))

    return Scenario(
        scenario_id=sid, snapshot_id=snap[0][0],
        city_ids=cities["city_id"], city_index={c: i for i, c in enumerate(cities["city_id"])},
        D_km=D_km, D_min=D_min,
        truck_ids=t.get("truck_id", []), truck_index={c: i for i, c in enumerate(t.get("truck_id", []))},
        truck_start=np.array(t.get("start_pos", []), dtype=np.int32),
        truck_cap=np.array(t.get("capacity_kg", []), dtype=float),
        truck_type=np.array(t.get("type", []), dtype=object),
        truck_cost_km=np.array(t.get("cost_per_km", []), dtype=float),
        truck_co2_km=np.array(t.get("co2_per_km", []), dtype=float),
        order_ids=o.get("order_id", []), order_index={c: i for i, c in enumerate(o.get("order_id", []))},
        order_pickup=np.array(o.get("pickup_pos", []), dtype=np.int32),
        order_delivery=np.array(o.get("delivery_pos", []), dtype=np.int32),
        order_weight=np.array(o.get("weight_kg", []), dtype=float),
        order_req_type=np.array(o.get("required_truck_type", []), dtype=object),
        order_value=np.array([np.nan if v is None else v for v in o.get("value", [])], dtype=float),
        pickup_tw=tw("pickup_tw_from", "pickup_tw_to") if m else np.zeros((0, 2), np.int32),
        delivery_tw=tw("delivery_tw_from", "delivery_tw_to") if m else np.zeros((0, 2), np.int32),
        order_priority=np.argsort(np.array(o.get("planning_order", []))).astype(np.int32),
        compat=compat, stats=stats,
    )


_RUN_COLS = ("score", "is_valid", "n_violations",
             "fulfillment", "cost_efficiency", "loaded_ratio", "co2_efficiency", "penalty", "late_penalty",
             "total_km", "loaded_km", "empty_km", "total_cost", "total_co2", "orders_fulfilled", "orders_total",
             "value_fulfilled", "value_lost_to_lateness", "value_total", "truck_utilization",
             "orders_late", "orders_too_late", "total_late_min", "penalized_late_min")
SOURCES = ("local", "validate", "simulate", "score")


def plan_hash(plan):
    """Stable hash of a plan (same stops => same hash), to match local and API runs."""
    canon = {t: [(s.get("action"), s.get("order")) for s in stops] for t, stops in plan.items() if stops}
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()[:16]


def save_run(con, sc, plan, result, algo=None, source="local", params=None):
    """Store one evaluated plan in results.*. `con` must be writable (connect(read_only=False)).

    plan:   API format {truck_id: [{"action": "pickup", "order": "O001"}, ...]}
    result: the API's JSON response for "validate" (ValidationResult), "simulate"
            (SimulationMetrics) or "score" (ScoreResult); for "local", any dict of the same
            shape produced by our own evaluator.
    Returns the run_id.
    """
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    result = result or {}
    metrics = result.get("metrics") or ({k: v for k, v in result.items()} if "total_km" in result else {})
    validation = result.get("validation") or (result if "is_valid" in result else {})
    flat = {**metrics, **(result.get("breakdown") or {})}
    flat["score"] = result.get("score")
    if validation:
        flat["is_valid"] = validation.get("is_valid")
        flat["n_violations"] = len(validation.get("violations") or [])
    trucks = metrics.get("trucks") or []

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    slim = {k: v for k, v in result.items() if k != "metrics"}
    if metrics:
        slim["metrics"] = {k: v for k, v in metrics.items() if k != "trucks"}
    cols = ("run_id", "scenario_id", "snapshot_id", "created_at", "algo", "params_json", "source",
            "plan_hash") + _RUN_COLS + ("plan_json", "response_json")
    vals = [run_id, sc.scenario_id, sc.snapshot_id, datetime.now(timezone.utc).replace(tzinfo=None),
            algo, json.dumps(params or {}), source, plan_hash(plan)] + \
           [flat.get(c) for c in _RUN_COLS] + [json.dumps(plan), json.dumps(slim, default=str)]
    con.execute("BEGIN")
    try:
        con.execute(f"INSERT INTO results.runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        v = [(run_id, x.get("rule"), x.get("truck"), x.get("order"), x.get("message"))
             for x in validation.get("violations") or []]
        if v:
            con.executemany("INSERT INTO results.run_violations VALUES (?,?,?,?,?)", v)
        tr = [(run_id, t.get("truck"), t.get("total_km"), t.get("loaded_km"), t.get("empty_km"), t.get("cost"),
               t.get("co2"), t.get("max_load_kg"), t.get("utilization"), t.get("finish_min"),
               t.get("driving_min"), t.get("break_and_rest_min"), t.get("route")) for t in trucks]
        if tr:
            con.executemany("INSERT INTO results.run_trucks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", tr)
        st = [(run_id, t.get("truck"), i, e.get("action"), e.get("order"), e.get("city"), e.get("arrival_min"),
               e.get("wait_min"), e.get("late_min"), e.get("departure_min"))
              for t in trucks for i, e in enumerate(t.get("schedule") or [])]
        if st:
            con.executemany("INSERT INTO results.run_stops VALUES (?,?,?,?,?,?,?,?,?,?)", st)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return run_id


if __name__ == "__main__":
    with connect() as con:
        for sid in list_scenarios(con):
            sc = load_scenario(con, sid)
            print(f"scenario {sid} (snapshot {sc.snapshot_id}): {sc.n_cities} cities, "
                  f"{sc.n_trucks} trucks, {sc.n_orders} orders, compat pairs={int(sc.compat.sum())}")
