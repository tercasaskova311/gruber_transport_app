#!/usr/bin/env bash
# End-to-end test against the fake API: fetch -> prepare -> checks -> load, plus change detection.
set -euo pipefail
PY="${PYTHON:-python3}"; export PYTHON="$PY"
cd "$(dirname "$0")/.."
export DATA_DIR="$(mktemp -d)"
export GRUBER_API="http://127.0.0.1:8765/Hackaton2026"
"$PY" tests/make_fixture.py --seed 1
"$PY" tests/fake_api.py 8765 & SRV=$!; trap 'kill $SRV' EXIT; sleep 1

echo "== 1st run: should create a snapshot";  ./run_all.sh
echo "== 2nd run: should say unchanged";       "$PY" fetch.py | grep -q unchanged && echo OK unchanged
"$PY" tests/make_fixture.py --seed 2
echo "== after fixture change: new snapshot";  "$PY" fetch.py
"$PY" - <<'PY'
import duckdb, os, load
con = load.connect()
n = con.execute("SELECT count(DISTINCT snapshot_id) FROM raw.snapshots").fetchall()[0][0]
assert n == 2, n
print(con.sql("SELECT scenario_id, order_id, time_window_type, pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to, time_window_slack_minutes, trucks_that_fit, planning_order FROM prep.order_features WHERE time_window_type<>'none' ORDER BY scenario_id, planning_order LIMIT 8"))
sc = load.load_scenario(con, "2")
assert sc.D_km.shape == (12, 12) and not (sc.D_km != sc.D_km.T).any()
assert (sc.delivery_tw[:, 0] <= sc.delivery_tw[:, 1]).all()
assert (sc.pickup_tw < load.INF).any() and (sc.delivery_tw < load.INF).any(), "ISO windows were not parsed"
con.close()
o = next(int(o) for o in sc.order_priority if sc.compat[o].any()); t = int(sc.compat[o].argmax())
tid, oid = sc.truck_ids[t], sc.order_ids[o]
plan = {tid: [{"action": "pickup", "order": oid}, {"action": "delivery", "order": oid}]}
# a response shaped like POST /Submissions/{id}/Score (Swagger: ScoreResult)
resp = {"scenario": sc.scenario_id, "score": 123.4,
        "breakdown": {"fulfillment": 2.5, "cost_efficiency": 50, "loaded_ratio": 60, "co2_efficiency": 40, "penalty": 0, "late_penalty": 0},
        "metrics": {"total_km": 100, "loaded_km": 60, "empty_km": 40, "orders_fulfilled": 1, "orders_total": sc.n_orders,
                    "trucks": [{"truck": tid, "route": ["C001", "C002"], "total_km": 100, "finish_min": 300,
                                "schedule": [{"action": "pickup", "order": oid, "city": "C001", "arrival_min": 0, "wait_min": 0, "late_min": 0, "departure_min": 30},
                                             {"action": "delivery", "order": oid, "city": "C002", "arrival_min": 120, "wait_min": 0, "late_min": 0, "departure_min": 150}]}]},
        "validation": {"is_valid": False, "violations": [{"rule": "unknown_order", "truck": tid, "order": "O999", "message": "x"}]}}
rw = load.connect(read_only=False)
rid = load.save_run(rw, sc, plan, resp, algo="test", source="score")
row = rw.execute("SELECT source, score, fulfillment, total_km, orders_fulfilled, is_valid, n_violations FROM results.runs WHERE run_id = ?", [rid]).fetchone()
assert row == ("score", 123.4, 2.5, 100.0, 1, False, 1), row
assert rw.execute("SELECT count(*) FROM results.run_stops WHERE run_id = ?", [rid]).fetchone()[0] == 2
assert rw.execute("SELECT count(*) FROM results.run_trucks WHERE run_id = ?", [rid]).fetchone()[0] == 1
assert rw.execute("SELECT rule FROM results.run_violations WHERE run_id = ?", [rid]).fetchone()[0] == "unknown_order"
assert load.plan_hash(plan) == load.plan_hash({**plan, "T_EMPTY": []})
print("saved run", rid)
PY
echo "ALL TESTS PASSED"
