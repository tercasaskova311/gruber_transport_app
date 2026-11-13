#!/usr/bin/env bash
# End-to-end test against the fake API: fetch -> prepare -> checks -> load, plus change detection.
set -euo pipefail
cd "$(dirname "$0")/.."
export DATA_DIR="$(mktemp -d)"
export GRUBER_API="http://127.0.0.1:8765/Hackaton2026"
python tests/make_fixture.py --seed 1
python tests/fake_api.py 8765 & SRV=$!; trap 'kill $SRV' EXIT; sleep 1

echo "== 1st run: should create a snapshot";  ./run_all.sh
echo "== 2nd run: should say unchanged";       python fetch.py | grep -q unchanged && echo OK unchanged
python tests/make_fixture.py --seed 2
echo "== after fixture change: new snapshot";  python fetch.py
python - <<'PY'
import duckdb, os, load
con = load.connect()
n = con.execute("SELECT count(DISTINCT snapshot_id) FROM snapshots").fetchall()[0][0]
assert n == 2, n
print(con.sql("SELECT scenario_id, order_id, tw_type, pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to, tw_slack_min, n_compatible_trucks, priority_rank FROM order_features WHERE tw_type<>'none' ORDER BY scenario_id, priority_rank LIMIT 8"))
sc = load.load_scenario(con, "2")
assert sc.D_km.shape == (12, 12) and not (sc.D_km != sc.D_km.T).any()
assert (sc.delivery_tw[:, 0] <= sc.delivery_tw[:, 1]).all()
assert (sc.pickup_tw < load.INF).any() and (sc.delivery_tw < load.INF).any(), "ISO windows were not parsed"
con.close()
rw = load.connect(read_only=False)
rid = load.save_run(rw, sc, "test", plan={"routes": []}, stops=[{"truck_id": sc.truck_ids[0], "seq": 0, "action": "start", "city_id": sc.city_ids[sc.truck_start[0]]}], local_score=0)
print("saved run", rid, rw.execute("SELECT count(*) FROM run_stops").fetchall()[0])
PY
echo "ALL TESTS PASSED"
