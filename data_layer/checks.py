"""checks.py : sanity checks on the prepared tables. Fails loudly.

Each ERROR check is a query that must return 0 rows; the rows it does return
are the offenders (printed). WARN checks print but don't fail.

    python checks.py
"""
import sys

import duckdb

try:
    from . import config as C
except ImportError:  # run as a script from database/ (python fetch.py)
    import config as C


class CheckFailed(Exception):
    pass


# The grain of every prep table: these columns must identify exactly one row.
# prep tables are built with CREATE TABLE AS (no constraints), so this check is
# what catches a join that forgot scenario_id and duplicated rows.
PREP_KEYS = {
    "city_index":          ("scenario_id", "city_pos"),
    "city_distances":      ("scenario_id", "from_pos", "to_pos"),
    "truck_features":      ("scenario_id", "truck_pos"),
    "order_base":          ("scenario_id", "order_pos"),
    "order_features":      ("scenario_id", "order_pos"),
    "order_truck_options": ("scenario_id", "order_pos", "truck_pos"),
    "scenario_summary":    ("scenario_id",),
}


def _key_check_sql():
    parts = []
    for table, cols in PREP_KEYS.items():
        key = ", ".join(cols)
        parts.append(f"""SELECT '{table}' AS table_name, concat_ws(' | ', {key}) AS key, count(*) AS n_rows,
                   bool_or({' OR '.join(f'{c} IS NULL' for c in cols)}) AS has_null
            FROM prep.{table} GROUP BY {key}
            HAVING count(*) > 1 OR bool_or({' OR '.join(f'{c} IS NULL' for c in cols)})""")
    return "\n        UNION ALL\n        ".join(parts) + "\n        LIMIT 20"


ERRORS = {
    "duplicate or NULL key in a prep table (see PREP_KEYS)": _key_check_sql(),
    "no current snapshot": """
        SELECT 'none' WHERE (SELECT count(*) FROM raw.cur_snapshots) = 0""",
    "counts differ from /Scenarios": """
        SELECT s.scenario_id, s.cities_count, st.n_cities, s.trucks_count, st.n_trucks, s.orders_count, st.n_orders
        FROM raw.cur_snapshots s JOIN prep.scenario_summary st USING (scenario_id)
        WHERE (s.cities_count IS NOT NULL AND s.cities_count <> coalesce(st.n_cities, 0))
           OR (s.trucks_count IS NOT NULL AND s.trucks_count <> coalesce(st.n_trucks, 0))
           OR (s.orders_count IS NOT NULL AND s.orders_count <> coalesce(st.n_orders, 0))""",
    "city_distances is not N*N": """
        SELECT c.scenario_id, c.n, l.n_rows
        FROM (SELECT scenario_id, count(*) n FROM prep.city_index GROUP BY ALL) c
        LEFT JOIN (SELECT scenario_id, count(*) n_rows FROM prep.city_distances GROUP BY ALL) l USING (scenario_id)
        WHERE coalesce(l.n_rows, 0) <> c.n * c.n""",
    "distance rows with unknown city": """
        SELECT d.scenario_id, d.from_city, d.to_city FROM raw.cur_distances d
        LEFT JOIN prep.city_index a ON a.scenario_id = d.scenario_id AND a.city_id = d.from_city
        LEFT JOIN prep.city_index b ON b.scenario_id = d.scenario_id AND b.city_id = d.to_city
        WHERE a.city_pos IS NULL OR b.city_pos IS NULL LIMIT 20""",
    "diagonal not 0": """
        SELECT scenario_id, from_city, km FROM prep.city_distances WHERE from_pos = to_pos AND km <> 0 LIMIT 20""",
    "missing or negative km": """
        SELECT scenario_id, from_city, to_city, km FROM prep.city_distances WHERE km IS NULL OR km < 0 LIMIT 20""",
    "matrix not symmetric": """
        SELECT a.scenario_id, a.from_city, a.to_city, a.km, b.km AS km_back
        FROM prep.city_distances a JOIN prep.city_distances b ON b.scenario_id = a.scenario_id AND b.from_pos = a.to_pos AND b.to_pos = a.from_pos
        WHERE a.from_pos < a.to_pos AND abs(a.km - b.km) > 1e-6 LIMIT 20""",
    "positions not contiguous 0..N-1": """
        SELECT 'city_index' t, scenario_id FROM prep.city_index GROUP BY ALL HAVING min(city_pos) <> 0 OR max(city_pos) <> count(DISTINCT city_pos) - 1 OR count(*) <> count(DISTINCT city_pos)
        UNION ALL
        SELECT 'truck_features', scenario_id FROM prep.truck_features GROUP BY ALL HAVING min(truck_pos) <> 0 OR max(truck_pos) <> count(DISTINCT truck_pos) - 1 OR count(*) <> count(DISTINCT truck_pos)
        UNION ALL
        SELECT 'order_features', scenario_id FROM prep.order_features GROUP BY ALL HAVING min(order_pos) <> 0 OR max(order_pos) <> count(DISTINCT order_pos) - 1 OR count(*) <> count(DISTINCT order_pos)""",
    "truck start city unknown": """
        SELECT scenario_id, truck_id, start_city FROM prep.truck_features WHERE start_pos IS NULL""",
    "order city unknown": """
        SELECT scenario_id, order_id, pickup_city, delivery_city FROM prep.order_features
        WHERE pickup_pos IS NULL OR delivery_pos IS NULL""",
    "bad truck numbers": """
        SELECT scenario_id, truck_id, capacity_kg, cost_per_km, co2_per_km, type FROM prep.truck_features
        WHERE coalesce(capacity_kg, 0) <= 0 OR cost_per_km IS NULL OR cost_per_km < 0
           OR co2_per_km IS NULL OR co2_per_km < 0 OR type IS NULL""",
    "bad order weight": """
        SELECT scenario_id, order_id, weight_kg FROM prep.order_features WHERE coalesce(weight_kg, 0) <= 0""",
    "time window from > to": """
        SELECT scenario_id, order_id, pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to
        FROM prep.order_features
        WHERE pickup_tw_from > pickup_tw_to OR delivery_tw_from > delivery_tw_to""",
}

WARNINGS = {
    "orders no truck can carry (type/capacity)": """
        SELECT scenario_id, order_id, weight_kg, required_truck_type FROM prep.order_features WHERE trucks_that_fit = 0""",
    "orders whose windows can't both be met (slack < 0)": """
        SELECT scenario_id, order_id, time_window_slack_minutes FROM prep.order_features WHERE time_window_slack_minutes < 0""",
    "orders no truck can serve solo on time": """
        SELECT scenario_id, order_id, trucks_that_fit FROM prep.order_features
        WHERE trucks_that_fit > 0 AND trucks_on_time = 0""",
    "orders with null value": """
        SELECT scenario_id, order_id FROM prep.order_features WHERE value IS NULL""",
    "orders whose time-window fields were not recognised (check raw_json!)": """
        SELECT o.scenario_id, o.id, o.raw_json FROM raw.cur_orders o
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
