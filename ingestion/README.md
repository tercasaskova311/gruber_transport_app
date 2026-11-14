# Data layer: what's in the database and how to use it

Everything lives in one DuckDB file, `data/hackathon.duckdb` (repo root). The file is git-ignored, so each person builds their own copy (see **Quick start**).
You can open it from Python, the DuckDB CLI (`duckdb data/hackathon.duckdb`), DBeaver, or the DuckDB UI.

## Quick start

```bash
cd ingestion
pip install -r ../requirements.txt  # from the repo root file
./run_all.sh                        # fetch API -> build prep tables -> run checks
```

* Run it again any time. It only stores a new snapshot if the API data changed. Use `./run_all.sh --force` to store one anyway.
* **SSL error on macOS** (`CERTIFICATE_VERIFY_FAILED`): run `open "/Applications/Python 3.12/Install Certificates.command"` once.
* **`python: command not found`**: the script uses `python3`. To pick another interpreter, use `PYTHON=.venv/bin/python ./run_all.sh`.
* **Upgrading from the old flat layout** (tables without `raw.`/`prep.`): delete `../data/hackathon.duckdb` and run `./run_all.sh --force`.

## 1. The big picture: three schemas

```
 Gruber API ──fetch.py──▶  raw.*  ──prepare.sql──▶  prep.*  ──load.py──▶  solver (numpy)
 (JSON / CSV)            append-only              rebuilt every run            │
                         + raw.cur_* views        + checks.py                  ▼
                                                        API responses ──load.save_run──▶ results.*
```

| Schema | What it holds | Written by | Rule |
|---|---|---|---|
| `raw` | API data exactly as fetched, one full copy per snapshot, plus `cur_*` views for the latest snapshot | `fetch.py` | **Never updated or deleted.** Every change in the data creates a new `snapshot_id`. |
| `prep` | Solver-ready tables: positions 0..N-1, distance matrix, drive times, feasibility, priorities | `prepare.sql` | **Dropped and rebuilt** on every run, in one transaction, so change the SQL freely. |
| `results` | Every plan we evaluated, with the API's score, metrics, violations and per-stop schedule | `load.save_run()` | Append only. This is how we compare algorithms. |

> **The join rule:** city, truck and order IDs repeat across scenarios (`C008` exists in several of them).
> **Always put `scenario_id` in your join condition.** Without it you get silent duplicates.

> **Solver code shouldn't need SQL.** Use `load.py` (section 5), which turns `prep.*` into numpy arrays.

## 2. The scenarios (current data)

| scenario_id | cities | trucks | orders | with time window | weight / capacity | total value |
|---|---|---|---|---|---|---|
| `scenario_small` | 10 | 4 | 20 | 0 % | 1.8 | 20 |
| `scenario_middle` | 20 | 8 | 50 | 14 % | 1.7 | 59 |
| `scenario_big` | 30 | 15 | 120 | 17 % | 3.0 | 145 |
| `scenario_competitive` | 45 | 25 | 200 | 32 % | 2.5 | 252.5 |

A weight / capacity ratio above 1 means the trucks can't carry everything at once, so they have to make several trips.
In every scenario, every order fits at least one truck and can be delivered on time by some truck serving it alone.
`scenario_competitive` allows **only 3 Score + 3 Simulate API calls**, so test locally first.

## 3. Rules from the challenge PDF that the data reflects

| Rule | Value | Where it shows up in the data |
|---|---|---|
| Truck types | `standard`, `refrigerated`, `hazmat`. An order with a `required_truck_type` may only go on that type; `NULL` = any truck. | `prep.order_truck_options`, `sc.compat` |
| Capacity | Load on board ≤ `capacity_kg` **at every moment**. A truck can carry several orders at once. | `capacity_kg`, `weight_kg` |
| Distances | Symmetric km matrix, 0 on the diagonal (great-circle × 1.3). Trucks do **not** return to their start city. | `prep.city_distances`, `sc.D_km` |
| Time | Minute `0` = Day 1, 06:00; all trucks start at minute 0. **Every time column is in minutes.** | all `*_min` / `*_tw_*` columns |
| Driving | 70 km/h, `driving_min = ceil(km × 60 / 70)` | `drive_minutes`, `sc.D_min` |
| Service | 30 min at every stop (pickup or delivery) | `prep.service_min()` |
| Breaks and rest | 45 min break after 4.5 h of driving; 11 h rest after 9 h of driving; waiting / service ≥ 45 min counts as a break | **not modelled in prep**: every timing column is optimistic |
| Early / late | Early = wait until `from`. Up to 60 min after `to`: still fulfilled, value drops linearly to 50 %. More than 60 min late: not fulfilled. | `alone_late_min`, `alone_value_factor` |
| Order value | 1.0 normal · 1.5 refrigerated/hazmat · **+0.5** with any window | `value` |
| Violations | −20 points each (wrong truck type, capacity exceeded, delivery before pickup, …) | |
| API limits | `scenario_competitive`: 3 Simulate + 3 Score calls per team; Validate is unlimited | `results.runs.source` |
| Data refresh | A server restart regenerates **all** scenarios (new cities) | `fetch.py` takes a new snapshot |

**Score** (max 1000, can be negative):

```
score = 10 × (0.50·fulfillment + 0.20·cost_eff + 0.15·loaded_ratio + 0.15·co2_eff) − 20 × violations

fulfillment  = 100 × value_fulfilled / value_total          (late orders count at reduced value)
cost_eff     = 100 × min(1, reference_cost / total_cost)
loaded_ratio = 100 × loaded_km / total_km
co2_eff      = 100 × min(1, reference_co2 / total_co2)

reference_km   = Σ direct pickup→delivery km of ALL orders × orders_fulfilled / orders_total
reference_cost = reference_km × cheapest cost_per_km in the fleet
reference_co2  = reference_km × lowest  co2_per_km  in the fleet
```

`prep.scenario_summary` already holds the inputs for the references: `ideal_km`, `min_cost_per_km` and `min_co2_per_km`.

## 4. Tables

Examples are real rows from `scenario_middle`.

### 4.1 `raw` schema: API data (`schema.sql`, filled by `fetch.py`)

Every raw table has `snapshot_id` and `scenario_id` columns and a `raw_json` column holding the original API object, untouched. `raw_json` is there in case we mapped a field wrong.
**Normally you read the `raw.cur_*` views**, which have the same columns but only the latest snapshot per scenario.

#### `raw.snapshots`: one row per (snapshot, scenario)
The log of fetches. It is written last in the fetch transaction, so a half-finished fetch is never visible.

| column | type | meaning | example |
|---|---|---|---|
| snapshot_id | VARCHAR | UTC time of the fetch, sortable | `20261113T203436220952Z` |
| scenario_id | VARCHAR | scenario | `scenario_middle` |
| fetched_at | TIMESTAMP | the same moment as a timestamp | `2026-11-13 20:34:36` |
| fingerprint | VARCHAR | sha256 of `/Scenarios` + every `/Cities`; a new snapshot is stored only when this changes | `3fcaaa6c…` |
| name | VARCHAR | scenario name | `Middle` |
| cities_count, trucks_count, orders_count | INTEGER | counts announced by `/Scenarios`, checked against the actual rows | `20, 8, 50` |

#### `raw.cities`: one row per city
| column | type | meaning | example |
|---|---|---|---|
| id | VARCHAR | city id (the same city can appear in several scenarios) | `C008` |
| name, country | VARCHAR | | `Cacak`, `RS` |
| latitude, longitude | DOUBLE | for maps | `43.89`, `20.35` |

#### `raw.trucks`: one row per truck
| column | type | meaning | example |
|---|---|---|---|
| id | VARCHAR | truck id | `T01` |
| start_city | VARCHAR | where the truck is at minute 0 | `C080` |
| capacity_kg | DOUBLE | maximum load at any moment | `18000` |
| type | VARCHAR | `standard` / `refrigerated` / `hazmat` | `standard` |
| cost_per_km | DOUBLE | € per km, loaded or empty | `1.40` |
| co2_per_km | DOUBLE | kg CO₂ per km, loaded or empty | `1.01` |

#### `raw.orders`: one row per transport order
| column | type | meaning | example |
|---|---|---|---|
| id | VARCHAR | order id | `O006` |
| pickup_city, delivery_city | VARCHAR | city ids | `C120`, `C060` |
| weight_kg | DOUBLE | | `6000` |
| required_truck_type | VARCHAR | `NULL` = any truck | `NULL` |
| value | DOUBLE | weight of this order in the fulfillment score | `1.5` |
| pickup_tw_from, pickup_tw_to | INTEGER | pickup window in minutes; `NULL` = no limit | `NULL, NULL` |
| delivery_tw_from, delivery_tw_to | INTEGER | delivery window in minutes | `525, 795` (Day 1 14:45 → 19:15) |

#### `raw.distances`: one row per (from_city, to_city)
The API's CSV matrix in long format. N cities give N×N rows, including the diagonal.

| column | type | meaning | example |
|---|---|---|---|
| from_city, to_city | VARCHAR | city ids | `C008`, `C010` |
| km | DOUBLE | road km | `43` |

#### `raw.cur_snapshots`, `raw.cur_cities`, `raw.cur_trucks`, `raw.cur_orders`, `raw.cur_distances` (views)
These have the same columns as the tables above, filtered to the **latest snapshot per scenario**. Everything downstream reads only these.

### 4.2 `prep` schema: solver-ready tables (`prepare.sql`)

All `*_pos` columns are **0-based and dense per scenario** (0…N-1), so you can use them directly as numpy row and column positions.
Positions are assigned by sorting IDs alphabetically.

| table | one row per | rows (small / middle / big / competitive) | use it for |
|---|---|---|---|
| `city_index` | city | 10 / 20 / 30 / 45 | city id ↔ matrix position |
| `city_distances` | (from, to) city pair | N² | distance and drive-time matrix |
| `truck_features` | truck | 4 / 8 / 15 / 25 | fleet, with positions and cost/CO₂ ranks |
| `order_features` | order | 20 / 50 / 120 / 200 | **the main order table** |
| `order_truck_options` | (order, truck) pair that *may* carry it | 80 / 323 / 1317 / 4104 | which trucks can carry an order, and the solo cost/time |
| `scenario_summary` | scenario | 4 | difficulty overview and scoring references |
| `order_base` | order | | internal helper; use `order_features` instead |

`prep` also contains two SQL macros: `prep.drive_minutes(km)` and `prep.service_min()`.

`prep` tables have no `PRIMARY KEY` constraints (they're built with `CREATE TABLE AS`). Instead, the key of every table is listed in `PREP_KEYS` in `checks.py`, and a duplicate or `NULL` key fails the build. If you add a `prep` table, add its key there too.

#### `prep.city_index`: key `(scenario_id, city_id)`
`raw.cur_cities` plus `city_pos`. Columns: `scenario_id, snapshot_id, city_id, name, country, latitude, longitude, city_pos`.

#### `prep.city_distances`: key `(scenario_id, from_pos, to_pos)`
| column | meaning | example |
|---|---|---|
| from_pos, to_pos | matrix position | `0, 1` |
| from_city, to_city | ids | `C008, C010` |
| km | | `43` |
| drive_minutes | `ceil(km × 60 / 70)`, without breaks | `37` |

#### `prep.truck_features`: key `(scenario_id, truck_id)`
| column | meaning | example |
|---|---|---|
| truck_pos | 0…T-1 | `1` |
| truck_id, start_city, capacity_kg, type, cost_per_km, co2_per_km | copied from raw | `T02, C048, 8000, refrigerated, 1.28, 0.82` |
| start_pos | city position of start_city | `8` |
| cost_rank | 1 = cheapest per km (ties share a rank) | `2` |
| co2_rank | 1 = cleanest per km | `1` |

#### `prep.order_features`: key `(scenario_id, order_id)`: **the main order table**
| column | meaning | example (`O038`) |
|---|---|---|
| order_pos | 0…M-1 | `37` |
| order_id, pickup_city, delivery_city, weight_kg, required_truck_type, value | copied from raw | `O038, C060, C045, 8400, NULL, 1.5` |
| pickup_pos, delivery_pos | city positions | `11, 7` |
| pickup_tw_from … delivery_tw_to | windows in minutes (`NULL` = none) | `345, 465, 870, 1020` |
| direct_km, direct_drive_min | the pickup → delivery leg | `387, 332` |
| time_window_type | `none` / `pickup` / `delivery` / `both` | `both` |
| earliest_pickup_minute | earliest pickup start (`pickup_tw_from`, or 0) | `345` |
| latest_pickup_minute | latest pickup arrival that still meets both windows when driving straight to the delivery (no breaks, so this is the best case); `NULL` = no deadline | `465` |
| time_window_slack_minutes | `latest − earliest`: how much freedom the order has; **< 0 = impossible even on its own** | `120` |
| trucks_that_fit | trucks with the right type and enough capacity | `7` |
| trucks_on_time | of those, how many are on time serving it alone (no breaks, so optimistic) | `3` |
| trucks_fulfillable | of those, how many are at most 60 min late serving it alone (still counts, at reduced value) | `3` |
| min_solo_cost | cheapest € to serve it alone | `988.8` |
| planning_order | **1 = plan first**. Sorted by smallest slack, then fewest trucks that fit, then highest value, then heaviest. | `1` |

#### `prep.order_truck_options`: key `(scenario_id, order_pos, truck_pos)`
This only has pairs where the type matches (or no type is required) and `weight_kg ≤ capacity_kg`.
"Alone" means the truck serves only this order: start (minute 0) → pickup → delivery, with service and waiting included but **no breaks or rests**, so these timings are optimistic.

| column | meaning | example |
|---|---|---|
| order_pos, order_id, truck_pos, truck_id | the pair | `0, O001, 3, T04` |
| empty_km_to_pickup | empty drive from the truck's start city | `245` |
| alone_km, alone_cost_eur, alone_co2_kg | totals for the solo trip | `490, 1058.4, 583.1` |
| pickup_arrival_min | arrival at the pickup city | `210` |
| delivery_arrival_min | arrival at the delivery city | `450` |
| alone_finish_min | when the delivery service ends | `480` |
| alone_late_min | worse of pickup / delivery lateness (0 = on time) | `0` |
| alone_on_time | `alone_late_min = 0` | `true` |
| alone_fulfillable | `alone_late_min ≤ 60`, so it still counts | `true` |
| alone_value_factor | share of the value kept: 1.0 on time … 0.5 at 60 min late … 0 beyond | `1.0` |

#### `prep.scenario_summary`: key `scenario_id`
| column | meaning |
|---|---|
| snapshot_id, name | which data this describes |
| n_cities, n_trucks, n_orders | sizes |
| total_weight_kg, total_capacity_kg, weight_capacity_ratio | above 1 means several trips are needed |
| max_order_kg, max_truck_kg | |
| total_value | `value_total` in the score |
| pct_with_tw | share of orders with any time window |
| ideal_km | Σ direct km of all orders, the score reference before multiplying by the fulfilled share |
| min_cost_per_km, min_co2_per_km | fleet minima used in the references |
| orders_no_truck_fits | orders no truck can carry (lost causes) |
| n_orders_tw_impossible | orders with slack < 0 |
| n_orders_no_solo_feasible | orders no truck can serve alone on time |
| n_orders_no_solo_fulfillable | orders no truck can serve alone even ≤ 60 min late |

### 4.3 `results` schema: every evaluated plan (`load.save_run`)

Column names are the API's own (Swagger `ScoreResult`, `SimulationMetrics`, `ValidationResult`, `TruckMetrics`, `ScheduleEntry`), so `load.save_run` stores an API response as it comes back.

#### `results.runs`: one row per evaluation · key `run_id`
| group | columns |
|---|---|
| identity | `run_id, scenario_id, snapshot_id` (the data the plan was built on), `created_at, algo, params_json` |
| source | `source`: `validate` / `simulate` / `score` (which API endpoint answered) or `local` (our own evaluator, same shape) · `plan_hash`: same plan ⇒ same hash |
| score | `score` (0–1000), `is_valid, n_violations` |
| breakdown | `fulfillment, cost_efficiency, loaded_ratio, co2_efficiency` (0–100 each), `penalty, late_penalty` (points) |
| metrics | `total_km, loaded_km, empty_km, total_cost, total_co2, orders_fulfilled, orders_total, value_fulfilled, value_lost_to_lateness, value_total, truck_utilization, orders_late, orders_too_late, total_late_min, penalized_late_min` |
| payload | `plan_json` (what was submitted), `response_json` (the full answer without per-truck detail) |

A Validate response only fills `is_valid` / `n_violations`, and a Simulate response has no `score` or breakdown. Missing values stay `NULL`.

#### `results.run_violations`: one row per violation
`run_id, rule, truck_id, order_id, message`

#### `results.run_trucks`: one row per truck per run · key `(run_id, truck_id)`
`total_km, loaded_km, empty_km, cost, co2, max_load_kg, utilization, finish_min, driving_min, break_and_rest_min, route` (city ids)

#### `results.run_stops`: one row per stop · key `(run_id, truck_id, seq)`
`seq` (0, 1, 2… per truck), `action, order_id, city_id, arrival_min, wait_min, late_min, departure_min`

## 5. Using it from the solver (`load.py`)

```python
import load

con = load.connect()                         # read-only; waits if fetch.py is writing
for sid in load.list_scenarios(con):         # scenario_big, _competitive, _middle, _small
    sc = load.load_scenario(con, sid)

sc = load.load_scenario(con, "scenario_small")
sc.D_km[i, j], sc.D_min[i, j]                # (N, N) km and drive minutes, by city position
sc.truck_start, sc.truck_cap, sc.truck_type, sc.truck_cost_km, sc.truck_co2_km   # (T,)
sc.order_pickup, sc.order_delivery           # (M,) city positions
sc.order_weight, sc.order_value, sc.order_req_type
sc.pickup_tw, sc.delivery_tw                 # (M, 2) [from, to]; no window = [0, load.INF]
sc.compat[o, t]                              # True if truck t may carry order o (type + capacity)
sc.order_priority                            # order positions, most urgent first
sc.service_min                               # 30
sc.stats                                     # the scenario_summary row as a dict

sc.order_ids[o], sc.truck_ids[t], sc.city_ids[c]   # position -> API id, for submitting
```

**Save every evaluated plan** so we can compare algorithms. `result` is the API's JSON response:

```python
plan = {"T01": [{"action": "pickup", "order": "O006"}, {"action": "delivery", "order": "O006"}]}
response = ...                                   # JSON from POST /Submissions/{id}/Score
rw = load.connect(read_only=False)
load.save_run(rw, sc, plan, response, algo="greedy", source="score", params={"seed": 1})
rw.close()
```

`source` is `validate`, `simulate` or `score` (whichever endpoint answered), or `local` for a dict of the same shape from our own evaluator.

DuckDB allows **one writing process at a time**. Close your writable connection when you're done, and don't run `fetch.py` while a solver is saving. Read-only connections can run alongside each other.

## 6. Useful queries

```sql
-- How hard is each scenario?
SELECT scenario_id, n_orders, n_trucks, weight_capacity_ratio, pct_with_tw
FROM prep.scenario_summary ORDER BY n_orders;

-- The 10 most urgent orders in a scenario
SELECT order_id, time_window_type, time_window_slack_minutes, trucks_that_fit, value
FROM prep.order_features WHERE scenario_id = 'scenario_big'
ORDER BY planning_order LIMIT 10;

-- Cheapest truck for each order when served alone (note scenario_id in the join!)
SELECT o.order_id, x.truck_id, x.alone_cost_eur, x.alone_on_time
FROM prep.order_features o
JOIN prep.order_truck_options x ON x.scenario_id = o.scenario_id AND x.order_pos = o.order_pos
WHERE o.scenario_id = 'scenario_middle'
QUALIFY row_number() OVER (PARTITION BY o.order_id ORDER BY x.alone_cost_eur) = 1;

-- Leaderboard: best score per scenario, algorithm and source
SELECT scenario_id, algo, source, max(score) AS best, count(*) AS runs
FROM results.runs WHERE score IS NOT NULL GROUP BY ALL ORDER BY scenario_id, best DESC;

-- Does our local score agree with the API? (same plan_hash)
SELECT l.scenario_id, l.algo, l.score AS local, a.score AS api, a.score - l.score AS diff
FROM results.runs l JOIN results.runs a USING (plan_hash, scenario_id)
WHERE l.source = 'local' AND a.source = 'score';

-- How many limited calls have we used on competitive?
SELECT source, count(*) FROM results.runs
WHERE scenario_id = 'scenario_competitive' AND source IN ('simulate', 'score') GROUP BY ALL;

-- Did the data change during the day? (one row per fetch that saw new data)
SELECT scenario_id, snapshot_id, fingerprint[:10] FROM raw.snapshots ORDER BY snapshot_id;
```

## 7. Files

| file | role |
|---|---|
| `run_all.sh` | fetch → prepare → checks in one command |
| `config.py` | API URL, paths, constants (speed, service time) |
| `schema.sql` | creates `raw.*` and `results.*` (safe to rerun) |
| `fetch.py` | API → `raw.*`; `--force`, `--scenario X`, `--watch --every 5`, `--on-change "cmd"` |
| `prepare.sql` / `prepare.py` | rebuilds `prep.*`, then runs checks |
| `checks.py` | sanity checks; fails loudly if the data is broken |
| `load.py` | `prep.*` → numpy `Scenario`; `save_run` → `results.*` |
| `tests/test_pipeline.sh` | offline end-to-end test against a fake API |
