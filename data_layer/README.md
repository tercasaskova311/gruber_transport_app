# DATA.md — what's in the database

A guide for the team: what each table holds, where it comes from, and how to query it.
Everything lives in one DuckDB file, `data/hackathon.duckdb`. You can open it from Python (`duckdb.connect(path, read_only=True)`), from the DuckDB CLI, or from DBeaver.

## 1. Pipeline

```
 Gruber API ──fetch.py──▶ RAW tables ──▶ cur_* views ──prepare.sql──▶ PRECOMPUTED tables ──load.py──▶ solver (numpy)
 (JSON/CSV)              append-only     latest snapshot            rebuilt every time                    │
                         + data/<snapshot>/ files                    + checks.py                          ▼
                                                                                              runs / run_stops (results)
```

* **Raw tables** (`snapshots, cities, trucks, orders, distances`) are never updated or deleted. Every fetch that sees new data adds a full new copy under a new `snapshot_id`.
* **`cur_*` views** show only the latest snapshot of each scenario. **Downstream code reads only `cur_*`**, never the raw tables.
* **Precomputed tables** are built from `cur_*` by `prepare.sql`. They're thrown away and rebuilt on every run, so you can change the SQL freely.
* **Output tables** (`runs, run_stops`) store every plan we tried and what the API said about it.

> **The join rule:** every table has `scenario_id`, and city/truck/order ids repeat across scenarios.
> **Always put `scenario_id` in your join condition.** Without it you get silent duplicates.

## 2. Domain rules the data encodes

| Rule | Value |
|---|---|
| Scenarios | `scenario_small` (10 cities / 4 trucks / 20 orders, no time windows), `scenario_middle` (20/8/50, ~10% with windows), `scenario_big` (30/15/120, ~20%), `scenario_competitive` (45/25/200, ~30%, **only 3 Score + 3 Simulate calls**) |
| Truck types | `standard`, `refrigerated`, `hazmat`. If an order has a `required_truck_type`, only that type may carry it; `null` means any truck can. |
| Capacity | The load on board must never exceed `capacity_kg`. A truck can carry several orders at once. |
| Distances | Symmetric km matrix with 0 on the diagonal (≈ great‑circle × 1.3). Trucks do **not** return to their start city. |
| Time | Minute `0` = Day 1, 06:00. Every time column is in **minutes since then**. |
| Driving | 70 km/h → `drive_min = ceil(km * 60 / 70)` |
| Service | 30 min at each stop (pickup or delivery) |
| Breaks | 45 min after 4.5 h of driving; 11 h rest after 9 h of driving. Waiting or service ≥ 45 min counts as a break. **Not included in our SQL estimates.** |
| Time windows | `{from, to}` on the pickup and/or delivery. Arriving early means waiting until `from`. Arriving up to 60 min after `to` still fulfills the order, but its value drops linearly from 100% to 50%. More than 60 min late means the order is **not fulfilled**. |
| Order value | normal 1.0 · refrigerated / hazmat 1.5 · **+0.5** if it has any time window |
| Violations | −20 points each (capacity exceeded, wrong truck type, delivery before pickup, …) |

**Score** (max 1000):

```
score = 10 × (0.50·fulfillment + 0.20·cost_eff + 0.15·loaded_ratio + 0.15·co2_eff) − 20 × violations

fulfillment  = 100 × value_fulfilled / value_total
cost_eff     = 100 × min(1, reference_cost / total_cost)
loaded_ratio = 100 × loaded_km / total_km
co2_eff      = 100 × min(1, reference_co2 / total_co2)

reference_km   = Σ direct pickup→delivery km of ALL orders × orders_fulfilled / orders_total
reference_cost = reference_km × cheapest cost_per_km in the fleet
reference_co2  = reference_km × lowest  co2_per_km  in the fleet
```

`scenario_stats.reference_km_all`, `min_cost_per_km` and `min_co2_per_km` give you these references directly.

## 3. Raw tables (`schema.sql`)

Each raw table has the key `(snapshot_id, scenario_id, id)` and a `raw_json` column holding the original API object, untouched.

### `snapshots`: one row per (snapshot, scenario)
This table records which fetch a row came from. It is written last, so a half‑finished fetch is never visible.

| column | type | meaning | example |
|---|---|---|---|
| snapshot_id | VARCHAR | UTC time of the fetch, sortable | `20261113T183224656430Z` |
| scenario_id | VARCHAR | scenario | `scenario_middle` |
| fetched_at | TIMESTAMP | same as snapshot_id, as a timestamp | `2026-11-13 18:32:24` |
| fingerprint | VARCHAR | sha256 of `/Scenarios` + every `/Cities`; when it changes, a new snapshot is taken | `bf3ecc…` |
| name | VARCHAR | scenario name | `Middle` |
| cities_count, trucks_count, orders_count | INTEGER | counts announced by `/Scenarios` (checked against the actual rows) | `20, 8, 50` |

### `cities`: one row per city
| column | type | meaning | example |
|---|---|---|---|
| id | VARCHAR | global city id, the same city in every scenario | `C008` |
| name, country | VARCHAR | | `Cacak`, `RS` |
| latitude, longitude | DOUBLE | for maps | `43.89`, `20.35` |

### `trucks`: one row per truck
| column | type | meaning | example |
|---|---|---|---|
| id | VARCHAR | truck id | `T01` |
| start_city | VARCHAR | where the truck is at minute 0 | `C001` |
| capacity_kg | DOUBLE | maximum load at any moment | `18000` |
| type | VARCHAR | `standard` / `refrigerated` / `hazmat` | `standard` |
| cost_per_km | DOUBLE | € per km, loaded or empty | `1.53` |
| co2_per_km | DOUBLE | kg CO₂ per km, loaded or empty | `0.61` |

### `orders`: one row per transport order
| column | type | meaning | example |
|---|---|---|---|
| id | VARCHAR | order id | `O001` |
| pickup_city, delivery_city | VARCHAR | city ids | `C080`, `C044` |
| weight_kg | DOUBLE | | `9000` |
| required_truck_type | VARCHAR | `NULL` = any truck | `NULL` |
| value | DOUBLE | weight of this order in the fulfillment score | `1.5` |
| pickup_tw_from / pickup_tw_to | INTEGER | from `pickup_window`, in minutes; `NULL` = no window | `NULL` |
| delivery_tw_from / delivery_tw_to | INTEGER | from `delivery_window`, in minutes | `1038`, `1278` (Day 1 23:18 → Day 2 03:18) |

### `distances`: one row per (from_city, to_city)
This is the API's CSV matrix in long format. With N cities it has N×N rows, including the diagonal.

| column | type | meaning | example |
|---|---|---|---|
| from_city, to_city | VARCHAR | | `C007`, `C028` |
| km | DOUBLE | road km | `412` |

### `cur_snapshots`, `cur_cities`, `cur_trucks`, `cur_orders`, `cur_distances`
These views have the same columns as the raw tables, filtered to the **latest `snapshot_id` per scenario**. Use them whenever you want "the data as it is now".

## 4. Precomputed tables (`prepare.sql`)

All indices (`idx`, `*_idx`) are **0‑based and dense per scenario**, so you can use them directly as numpy row and column positions. Ids are sorted alphabetically to assign them.

### `city_idx`: one row per city · key `(scenario_id, city_id)`
`cur_cities` plus `idx` (0…N‑1), the row and column of the distance matrices.
Columns: `scenario_id, snapshot_id, city_id, name, country, latitude, longitude, idx`.

### `legs`: one row per (from, to) city pair · key `(scenario_id, from_idx, to_idx)`
This is the full matrix with indices and drive time. It's built from `cur_distances` joined to `city_idx` twice.

| column | meaning | example |
|---|---|---|
| from_idx, to_idx | matrix position | `3, 7` |
| from_city, to_city | ids | `C028, C099` |
| km | | `824` |
| drive_min | `ceil(km*60/70)`, without breaks | `707` |

### `truck_features`: one row per truck · key `(scenario_id, truck_id)`
`cur_trucks` plus indices and ranks.

| column | meaning | example |
|---|---|---|
| idx | truck position 0…T‑1 | `0` |
| truck_id, start_city, capacity_kg, type, cost_per_km, co2_per_km | copied from raw | `T01, C136, 18000, standard, 1.53, 0.61` |
| start_idx | city idx of start_city | `19` |
| cost_rank | 1 = cheapest per km (ties share a rank) | `7` |
| co2_rank | 1 = cleanest per km | `1` |

### `order_base`: one row per order · key `(scenario_id, order_id)`
`cur_orders` plus indices, the direct leg and time‑window maths. This is a helper table; use `order_features` instead, which contains every column here and more.

### `order_features`: one row per order · key `(scenario_id, order_id)`
This is the main order table for the solver. It's built from `order_base` plus counts from `order_truck_compat`.

| column | meaning | example |
|---|---|---|
| order_idx | order position 0…M‑1 | `25` |
| order_id, pickup_city, delivery_city, weight_kg, required_truck_type, value | copied from raw | `O026, C076, C049, 6000, NULL, 1.5` |
| pickup_idx, delivery_idx | city idx | `9, 4` |
| pickup_tw_from … delivery_tw_to | windows in minutes (`NULL` = none) | `NULL, NULL, 272, 512` |
| direct_km, direct_drive_min | pickup → delivery leg | `470, 403` |
| tw_type | `none` / `pickup` / `delivery` / `both` | `delivery` |
| earliest_pickup_min | earliest pickup start (= `pickup_tw_from`, or 0) | `0` |
| latest_pickup_min | latest pickup start that still makes both windows when driving straight to the delivery. `NULL` = no deadline. | `79` (= 512 − 30 − 403) |
| tw_slack_min | `latest − earliest`: how much freedom the order has. **< 0 means impossible even on its own.** | `79` |
| n_compatible_trucks | trucks with the right type and enough capacity | `8` |
| n_feasible_trucks | of those, how many reach it on time alone (start → pickup → delivery, no breaks) | `0` |
| min_solo_cost | cheapest € to serve it alone | `930.9` |
| priority_rank | 1 = plan first. Sorted by smallest slack, then fewest trucks, then highest value. | `1` |

### `order_truck_compat`: one row per (order, truck) that *may* carry it · key `(scenario_id, order_idx, truck_idx)`
This table only has pairs where the type matches (or no type is required) and `weight_kg ≤ capacity_kg`. "Solo" means the truck serves only this order: start → pickup → delivery, waiting when early, and **no breaks**.

| column | meaning | example |
|---|---|---|
| order_idx, order_id, truck_idx, truck_id | the pair | `2, O003, 5, T06` |
| start_to_pickup_km | empty drive from the truck's start | `655` |
| est_solo_km / est_solo_cost / est_solo_co2 | total km, €, CO₂ for the solo trip | `1479 / 1375.5 / 990.9` |
| pickup_start_min | when pickup service starts | `562` |
| delivery_arrival_min | arrival at the delivery city | `1299` |
| est_solo_late_min | worst lateness at pickup or delivery (0 = on time) | `0` |
| est_solo_feasible | on time, full value | `true` |
| est_solo_fulfillable | ≤ 60 min late, so still counts at reduced value | `true` |

### `order_pairs`: one row per pair of orders a < b · key `(scenario_id, a_idx, b_idx)`
This shows how good a candidate two orders are to share a truck, which is useful for clustering and LNS removal. It has M·(M‑1)/2 rows.

| column | meaning | example |
|---|---|---|
| a_idx, b_idx | order idx, a < b | `34, 43` |
| pickup_km | km between the two pickup cities | `458` |
| delivery_km | km between the two delivery cities | `710` |
| relatedness | **lower = more related**. Computed as (pickup_km + delivery_km) / (2 × longest leg) + earliest‑pickup gap in days + 1 if the required types differ | `1.71` |

### `scenario_stats`: one row per scenario · key `scenario_id`
A quick difficulty overview, and the reference values used in scoring.

| column | meaning | example |
|---|---|---|
| n_cities, n_trucks, n_orders | | `20, 8, 50` |
| total_weight_kg, total_capacity_kg, weight_capacity_ratio | above 1 means trucks must do several trips | `351000, 162000, 2.17` |
| max_order_kg, max_truck_kg | | `15000, 24000` |
| total_value | = `value_total` in the score | `66.0` |
| pct_with_tw | share of orders with a window | `0.34` |
| reference_km_all | Σ direct km of all orders (score reference before the × fulfilled share) | `20591` |
| min_cost_per_km, min_co2_per_km | the fleet minima used in the references | `0.93, 0.61` |
| n_orders_no_truck | orders no truck can carry, a lost cause | `0` |
| n_orders_tw_impossible | slack < 0 | `0` |
| n_orders_no_solo_feasible | no truck reaches them on time alone | `1` |

## 5. Output tables (results)

### `runs`: one row per plan we evaluated · key `run_id`
Column names are the API's own names, so `load.save_run(con, sc, algo, plan, api_result=response.json())` fills them.

| group | columns |
|---|---|
| identity | `run_id, scenario_id, snapshot_id` (the data the plan was built on), `created_at, algo, params_json, source` (`local/validate/simulate/score`) |
| score | `local_score` (our evaluator), `api_score`, `is_valid`, `violations` |
| breakdown (0–100) | `fulfillment, cost_efficiency, loaded_ratio, co2_efficiency, penalty, late_penalty` |
| metrics | `total_km, loaded_km, empty_km, total_cost, total_co2, orders_fulfilled, orders_total, value_fulfilled, value_lost_to_lateness, value_total, truck_utilization, orders_late, orders_too_late, total_late_min, penalized_late_min` |
| payload | `plan_json` (what we submitted), `response_json` (the full API answer) |

### `run_stops`: one row per stop of a plan · key `(run_id, truck_id, seq)`
This comes from the API's `trucks[].schedule`.
Columns: `run_id, truck_id, seq, action (pickup/delivery), order_id, city_id, arrival_min, wait_min, late_min, departure_min, load_kg`.

## 6. Useful queries

```sql
-- What's loaded, and how hard is each scenario?
SELECT scenario_id, snapshot_id, n_orders, n_trucks, weight_capacity_ratio, pct_with_tw, n_orders_no_truck
FROM scenario_stats ORDER BY n_orders;

-- The 10 most urgent orders in a scenario
SELECT order_id, tw_type, tw_slack_min, n_compatible_trucks, value
FROM order_features WHERE scenario_id = 'scenario_big'
ORDER BY priority_rank LIMIT 10;

-- Cheapest truck for each order when served alone (note scenario_id in the join!)
SELECT o.order_id, c.truck_id, c.est_solo_cost, c.est_solo_late_min
FROM order_features o
JOIN order_truck_compat c ON c.scenario_id = o.scenario_id AND c.order_idx = o.order_idx
WHERE o.scenario_id = 'scenario_middle'
QUALIFY row_number() OVER (PARTITION BY o.order_id ORDER BY c.est_solo_cost) = 1;

-- The 5 orders most worth combining with order O007
SELECT CASE WHEN a.order_id = 'O007' THEN b.order_id ELSE a.order_id END AS other, p.relatedness
FROM order_pairs p
JOIN order_features a ON a.scenario_id = p.scenario_id AND a.order_idx = p.a_idx
JOIN order_features b ON b.scenario_id = p.scenario_id AND b.order_idx = p.b_idx
WHERE p.scenario_id = 'scenario_middle' AND 'O007' IN (a.order_id, b.order_id)
ORDER BY p.relatedness LIMIT 5;

-- Best API score so far per scenario
SELECT scenario_id, max(api_score) AS best, count(*) AS attempts
FROM runs WHERE api_score IS NOT NULL GROUP BY ALL;

-- Did the data change during the day? (one row per fetch that saw new data)
SELECT scenario_id, snapshot_id, fingerprint[:10] FROM snapshots ORDER BY snapshot_id;
```

From Python, skip SQL and get numpy arrays directly:

```python
import load
sc = load.load_scenario(load.connect(), "scenario_middle")
sc.D_km, sc.D_min                 # (N, N) matrices, indexed by city idx
sc.order_pickup, sc.order_delivery, sc.order_weight, sc.order_value
sc.pickup_tw, sc.delivery_tw      # (M, 2) [from, to]; no window = [0, load.INF]
sc.compat[o, t]                   # True if truck t may carry order o
sc.order_priority                 # order idx, most urgent first
```
