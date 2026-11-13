"""checks.py : sanity checks on the prepared tables. Fails loudly.

Each ERROR check is a query that must return 0 rows; the rows it does return
are the offenders (printed). WARN checks print but don't fail.

    python checks.py
"""
import sys

import duckdb

import config as C


class CheckFailed(Exception):
    pass


ERRORS = {
    "no current snapshot": """
        SELECT 'none' WHERE (SELECT count(*) FROM cur_snapshots) = 0""",
    "counts differ from /Scenarios": """
        SELECT s.scenario_id, s.cities_count, st.n_cities, s.trucks_count, st.n_trucks, s.orders_count, st.n_orders
        FROM cur_snapshots s JOIN scenario_stats st USING (scenario_id)
        WHERE (s.cities_count IS NOT NULL AND s.cities_count <> coalesce(st.n_cities, 0))
           OR (s.trucks_count IS NOT NULL AND s.trucks_count <> coalesce(st.n_trucks, 0))
           OR (s.orders_count IS NOT NULL AND s.orders_count <> coalesce(st.n_orders, 0))""",
    "legs is not N*N": """
        SELECT c.scenario_id, c.n, l.n_legs
        FROM (SELECT scenario_id, count(*) n FROM city_idx GROUP BY ALL) c
        LEFT JOIN (SELECT scenario_id, count(*) n_legs FROM legs GROUP BY ALL) l USING (scenario_id)
        WHERE coalesce(l.n_legs, 0) <> c.n * c.n""",
    "distance rows with unknown city": """
        SELECT d.scenario_id, d.from_city, d.to_city FROM cur_distances d
        LEFT JOIN city_idx a ON a.scenario_id = d.scenario_id AND a.city_id = d.from_city
        LEFT JOIN city_idx b ON b.scenario_id = d.scenario_id AND b.city_id = d.to_city
        WHERE a.idx IS NULL OR b.idx IS NULL LIMIT 20""",
    "diagonal not 0": """
        SELECT scenario_id, from_city, km FROM legs WHERE from_idx = to_idx AND km <> 0 LIMIT 20""",
    "missing or negative km": """
        SELECT scenario_id, from_city, to_city, km FROM legs WHERE km IS NULL OR km < 0 LIMIT 20""",
    "matrix not symmetric": """
        SELECT a.scenario_id, a.from_city, a.to_city, a.km, b.km AS km_back
        FROM legs a JOIN legs b ON b.scenario_id = a.scenario_id AND b.from_idx = a.to_idx AND b.to_idx = a.from_idx
        WHERE a.from_idx < a.to_idx AND abs(a.km - b.km) > 1e-6 LIMIT 20""",
    "idx not contiguous 0..N-1": """
        SELECT 'city_idx' t, scenario_id FROM city_idx GROUP BY ALL HAVING min(idx) <> 0 OR max(idx) <> count(DISTINCT idx) - 1 OR count(*) <> count(DISTINCT idx)
        UNION ALL
        SELECT 'truck_features', scenario_id FROM truck_features GROUP BY ALL HAVING min(idx) <> 0 OR max(idx) <> count(DISTINCT idx) - 1 OR count(*) <> count(DISTINCT idx)
        UNION ALL
        SELECT 'order_features', scenario_id FROM order_features GROUP BY ALL HAVING min(order_idx) <> 0 OR max(order_idx) <> count(DISTINCT order_idx) - 1 OR count(*) <> count(DISTINCT order_idx)""",
    "truck start city unknown": """
        SELECT scenario_id, truck_id, start_city FROM truck_features WHERE start_idx IS NULL""",
    "order city unknown": """
        SELECT scenario_id, order_id, pickup_city, delivery_city FROM order_features
        WHERE pickup_idx IS NULL OR delivery_idx IS NULL""",
    "bad truck numbers": """
        SELECT scenario_id, truck_id, capacity_kg, cost_per_km, co2_per_km, type FROM truck_features
        WHERE coalesce(capacity_kg, 0) <= 0 OR cost_per_km IS NULL OR cost_per_km < 0
           OR co2_per_km IS NULL OR co2_per_km < 0 OR type IS NULL""",
    "bad order weight": """
        SELECT scenario_id, order_id, weight_kg FROM order_features WHERE coalesce(weight_kg, 0) <= 0""",
    "time window from > to": """
        SELECT scenario_id, order_id, pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to
        FROM order_features
        WHERE pickup_tw_from > pickup_tw_to OR delivery_tw_from > delivery_tw_to""",
}

WARNINGS = {
    "orders no truck can carry (type/capacity)": """
        SELECT scenario_id, order_id, weight_kg, required_truck_type FROM order_features WHERE n_compatible_trucks = 0""",
    "orders whose windows can't both be met (slack < 0)": """
        SELECT scenario_id, order_id, tw_slack_min FROM order_features WHERE tw_slack_min < 0""",
    "orders no truck can serve solo on time": """
        SELECT scenario_id, order_id, n_compatible_trucks FROM order_features
        WHERE n_compatible_trucks > 0 AND n_feasible_trucks = 0""",
    "orders with null value": """
        SELECT scenario_id, order_id FROM order_features WHERE value IS NULL""",
    "orders whose time-window fields were not recognised (check raw_json!)": """
        SELECT o.scenario_id, o.id, o.raw_json FROM cur_orders o
        WHERE o.pickup_tw_from IS NULL AND o.pickup_tw_to IS NULL
          AND o.delivery_tw_from IS NULL AND o.delivery_tw_to IS NULL
          AND regexp_matches(lower(o.raw_json::VARCHAR), '"[a-z_]*(window|tw)[a-z_]*"\\s*:\\s*(\\[\\s*[^\\]\\s]|\\{\\s*[^}\\s]|[0-9"])')""",
}


def _report(con, name, sql, level):
    rows = con.execute(sql).fetchall()
    if rows:
        cols = [d[0] for d in con.description]
        print(f"  {level}: {name} ({len(rows)} rows)  cols={cols}", file=sys.stderr)
        for r in rows[:10]:
            print(f"      {r}", file=sys.stderr)
    return len(rows)


def run(con):
    failed = [name for name, sql in ERRORS.items() if _report(con, name, sql, "ERROR")]
    n_warn = sum(1 for name, sql in WARNINGS.items() if _report(con, name, sql, "WARN"))
    if failed:
        raise CheckFailed(f"CHECKS FAILED: {', '.join(failed)}")
    print(f"checks OK ({len(ERRORS)} passed, {n_warn} warnings)", flush=True)


if __name__ == "__main__":
    with duckdb.connect(str(C.DB_PATH), read_only=True) as con:
        try:
            run(con)
        except CheckFailed as e:
            print(e, file=sys.stderr)
            sys.exit(1)
