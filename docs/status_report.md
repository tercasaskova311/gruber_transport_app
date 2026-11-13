# Status report: Gruber "Logistics Grand Prix" solver (2026-11-14)

Purpose: hand-over to plan the next steps. Everything below was verified by running code;
numbers are from the local exact simulator unless marked otherwise.

## 1. The problem in one paragraph

Pickup-and-delivery routing with a heterogeneous fleet (capacity, truck type: standard /
refrigerated / hazmat), soft time windows (up to 60 min late keeps 100 % → 50 % of the
order's value, more than 60 min late = not fulfilled), automatic driver breaks and rests, and
open routes (trucks don't return). A plan maps truck ID → ordered list of pickup/delivery
stops. The API simulates it and returns a score (max 1000):

```
score = 10 × (0.50·fulfillment + 0.20·cost_eff + 0.15·loaded_ratio + 0.15·co2_eff) − 20 × violations
fulfillment  = 100 × value_fulfilled / value_total
cost_eff     = 100 × min(1, reference_cost / total_cost)
co2_eff      = 100 × min(1, reference_co2 / total_co2)
loaded_ratio = 100 × loaded_km / total_km
reference_km = Σ direct pickup→delivery km of ALL orders × orders_fulfilled / orders_total
reference_cost / co2 = reference_km × cheapest cost_per_km / lowest co2_per_km in the fleet
```

Order value: 1.0 normal, 1.5 refrigerated/hazmat, +0.5 with any time window (the API sends
`value`). Spec: `docs/Hackaton2026.pdf`; API docs mirror: `docs/api_documentation.txt`,
`docs/swagger.json`.

Scenarios (data regenerates on every server restart; organizers may publish final scenarios):

| id | cities | trucks | orders | orders with window |
|---|---|---|---|---|
| scenario_small | 10 | 4 | 20 | 0 |
| scenario_middle | 20 | 8 | 50 | 7 |
| scenario_big | 30 | 15 | 120 | 20 |
| scenario_competitive | 45 | 25 | 200 | 63 |

## 2. Hard constraints for whoever continues

- **API calls:** Validate and all `GET /Scenarios...` are free. **Never call Simulate or Score
  without asking the user in chat first** (state scenario, number of calls, reason); a yes
  covers only that batch. `scenario_competitive` allows only **3 Simulate + 3 Score calls in
  total** per team; the client refuses them without `--i-am-sure`, and that flag must never be
  passed by the assistant. Code paths that call Simulate/Score print the payload and ask y/n.
- **Git:** do not commit or push. Make and test changes, then tell the user to commit.
- **Generic solver:** no scenario-specific hardcoding (data changes on restart). Judge changes on
  all snapshots × several seeds, not one run.
- **Zero violations:** every violation costs 20 points; plans must be checked with the exact
  simulator before any submission.
- **Dependencies:** keep minimal (requests, numpy, pytest; the solver itself is stdlib-only;
  `data_layer` uses duckdb). Ask before adding more.
- API key lives in a git-ignored `.env` (`GRUBER_BASE_URL`, `GRUBER_API_KEY`); never print it.

## 3. Repository and branches

Team repo: `https://repos.hackathon.bz.it/2026-sfscon/team-5.git` (remote name `team5`).

| Branch | Contents | State |
|---|---|---|
| `main` | README, LICENSE | |
| `data-layer` | `data_layer/` (teammate): DuckDB pipeline | pushed |
| `simulator` | `gruber/`, `tools/`, `tests/`, `docs/`, `data/` + merged `data-layer` | pushed |
| `solver` | everything in `simulator` + `solver/` (teammate) + evaluator fix | pushed (`d1aaf65`) |

Uncommitted in the working tree: `tools/missed_orders.py` (section 7), this report.

Note: `solver` got `simulator` via a squash commit ("Merge simulator into solver" has one
parent), so git does not know `simulator` is contained in `solver`. Future merges should be
real merges.

### Layout

```
gruber/            shared base (package)
  config.py        base URL + key from env/.env
  api.py           client for all endpoints; Simulate/Score guarded (y/n, competitive needs i_am_sure)
  snapshot.py      download a scenario into data/<scenario>/<timestamp>/
  loader.py        load(sid, snapshot=None) -> Scenario; from_raw(...) for other data sources
  simulator.py     EXACT copy of API Validate/Simulate/Score: simulate(), score(), api_round()
  cli.py           fetch | local <sid> <plan> | validate <sid> <plan>
  README.md        usage for teammates
tools/
  parity.py        build / send (asks y/n) / compare: API responses vs local simulator
  validate_fuzz.py random plans vs free Validate endpoint
  plangen.py       random valid / invalid plan generator (test only)
  missed_orders.py diagnosis of unfulfilled orders (uncommitted)
tests/
  test_simulator.py          unit tests + 156 saved API parity cases
  test_solver_evaluator.py   solver/evaluator.py vs gruber/simulator.py
solver/            teammate's solver (stdlib only, flat imports, run from inside or via path)
  instance.py      loads a folder of cities/trucks/orders/distance_matrix.json -> Instance
  evaluator.py     fast per-truck simulation (resumable from saved state) + score formula
  solver.py        ΔS insertion (greedy/regret), ALNS (5 destroy, 4 repair, SA, adaptive weights)
  run.py           build -> ALNS -> compare -> out/ (plan_optimized.json etc.)
  compare.py       before/after report; make_fake_scenario.py; fetch_data.py
data_layer/        teammate's DuckDB pipeline: raw.* (snapshots), prep.* (features), results.*
data/<scenario>/<ts>/   JSON snapshots (cities, trucks, orders, distance_matrix(.json/.csv), sample_plan)
data/parity/       parity plan sets + saved API responses (156)
docs/semantics.md  verified API behaviour (the reference for all rules)
```

All tests: `python -m pytest -q tests` → 175 passed.

## 4. Milestone 1 done: exact local simulator

`gruber/simulator.py` reproduces the API exactly:

- **Validation:** 120 random plans (mostly invalid) give identical violation lists from the free
  Validate endpoint and the local code (rule, truck, order, message, order of listing).
- **Simulate/Score:** 156 responses on small/middle/big (77 plans incl. long routes with rests,
  time-window-heavy plans, plans 1–60 min late, invalid plans; plus 2 lateness probes) match
  field by field incl. every schedule entry, with zero tolerance after the API's rounding.

API calls used so far: 156 Simulate/Score (small/middle/big, approved), ~400 Validate (free).
**Zero calls on scenario_competitive.**

Behaviour not in the PDF (full list: `docs/semantics.md`):

- Order fields: `pickup_window` / `delivery_window` = `{"from","to"}` minutes or null; `value`.
- **Breaks:** time standing still (waiting + service, summed over consecutive same-city stops)
  counts toward the next pause; only `45 − standing` (or `660 − standing`) is inserted.
  Standing ≥ 45 min before driving resets the 4.5 h counter. Breaks can interrupt a leg.
- Driving minutes = `ceil(km·60/70)` per leg; 30 min service per stop; early arrival waits.
- Order late at both stops: value decay and the 60 min cut-off use the **max**;
  `penalized_late_min` sums both. `orders_late` includes too-late orders.
- `truck_type_mismatch` is reported at every stop of the order until it is loaded; the order is
  still carried (counts for capacity) but never fulfilled.
- Capacity-rejected pickups are not driven to; their deliveries are silently ignored.
- Rounding: score, breakdown, cost, CO₂ to 2 decimals; utilization and values to 4.
- Unverified but unreachable with current data: standing ≥ 11 h counting as a daily rest
  (max standing time is ~625 min). `simulate()` returns `_unverified` notes if a plan hits it.

Speed: full plan ~1.6 ms (big), ~2.7 ms (competitive); one route ~0.34 ms.

## 5. The teammate's solver (branch `solver`)

Approach: insert each order at the position with the highest exact score gain ΔS
(time-window orders first by regret-3; greedy, regret-2 and regret-3 starts, best kept), then
ALNS: destroy random / worst / Shaw / whole route / around longest empty legs, repair greedy /
noisy / regret-2 / regret-3, simulated annealing, adaptive weights. Speed tricks: resume a route
simulation from the saved state at the insertion point; pre-rank positions by extra km and
fully simulate only the best `topk`; cache best insertion per (order, truck).

Run on our real snapshots: `python solver/run.py <snapshot_dir> --time 20 --seed 1` (writes
`<snapshot_dir>/out/`; use a copy of the snapshot folder to keep the repo clean).

**Evaluator fix (done, pushed):** `solver/evaluator.py` used a wrong break rule (always a full
45/660 min pause; per-stop wait+service check), which made 4–8 % of routes finish 15–75 min
later than the API (never earlier). Fixed to the verified rule; the resume state now carries
standing time. `tests/test_solver_evaluator.py` compares `simulate_truck` with
`gruber.simulator` on random routes from all four snapshots (identical km, cost, CO₂, finish,
driving, breaks, value) and checks resume-from-state = full simulation. Before the fix 4 of 8
tests failed; now all pass.

### Results (exact simulator, 0 violations everywhere)

20 s ALNS, seed 1, single process:

| scenario | score | fulfilled | F | cost_eff | loaded | co2_eff |
|---|---|---|---|---|---|---|
| small | 1000.00 | 20/20 | 100 | 100 | 100 | 100 |
| middle | 997.27 | 50/50 | 100 | 100 | 98.18 | 100 |
| big | 969.83 | 115/120 | 94.48 | 100 | 98.28 | 100 |
| competitive | 910.62 | 173/200 | 82.25 | 100 | 99.57 | 100 |

Old vs fixed evaluator, 3 seeds × 30 s, 12 processes in parallel (CPU-starved: only 30–100
ALNS iterations each, so this mostly measures construction):

| | old | fixed |
|---|---|---|
| big | 969.73 mean, 115/120 | 969.68 mean, 115/120 |
| competitive | 911.00 mean, 173/200 | 908.03 mean, 172/200 |

Differences are within noise: the evaluator fix is a correctness fix, not a score gain.
ALNS throughput on competitive is low (~150–300 iterations per 20 s alone).

## 6. Where the remaining points are

- **cost_eff and co2_eff are already 100** on all scenarios (consolidation beats the reference;
  both are capped at 100). Extra km only cost a little loaded ratio.
- Loaded ratio is ~98–100.
- **Fulfillment is the only big lever:** big misses 5 orders, competitive 27–28. On competitive
  the missed value is 44.5 of 252.5 → up to **+88 points** if all were served (not achievable,
  see below).
- Structural fact from the spec: **there is no planning horizon**, so an order without a time
  window can always be appended at the end of some compatible route and fulfilled. Routes of
  70+ days are legal (one truck currently finishes at minute 102,866). The hard part is only the
  time-window orders (63 on competitive).
- Windows are generated so that the **nearest compatible truck serving the order alone** is on
  time, so window orders compete for the few trucks that start near them, early in their routes.

## 7. Diagnosis of the competitive plan (`tools/missed_orders.py`)

`python -m tools.missed_orders scenario_competitive <plan.json> [--json out.json]` (~1 min).
For each unfulfilled order: compatible trucks, trucks that can serve it alone on time, and the
best insertion into each compatible truck's current route that keeps every order already on it
fulfilled at no less value, with the exact score change.

On the competitive plan (911.45, 172/200):

- All 28 missed orders have time windows; all of them can be served on time by 1–5 trucks
  driving to them alone.
- **3 orders (O032, O039, O140) have a score-improving insertion right now**, all on truck
  **T12, which is completely unused** (+1.14 to +2.33 each). The solver missed them because ALNS
  repair only considers the 8 nearest trucks (`max_trucks=8`), the 3 best positions by km
  (`topk=3`) and retries only 8 unassigned orders per iteration (`bank_retry=8`), with few
  iterations.
- **25 orders are blocked:** the trucks able to reach them in time are already busy at that
  point of their route. 13 orders have exactly one on-time truck (T21 is the only one for 5 of
  them, T15 for 3), so 200/200 is likely impossible. Some needed trucks are nearly idle (T09,
  T20, T05 carry one order each) but that one order occupies the needed time slot, so it would
  have to move to another truck first; no current operator does this deliberately.

## 8. Proposed next steps (not started)

Ordered by effort; all generic, none instance-specific:

1. **Unassigned-pool sweep:** after ALNS (and periodically during it), try every unassigned
   order on every compatible truck at every position; accept positive ΔS. Should capture the T12
   gains at once.
2. **Targeted ("blocking") removal operator:** for an unserved time-window order, remove the
   orders occupying the early part of the routes of the trucks that can reach it in time, then
   reinsert with the unserved order first.
3. **Time-window-first decomposition:** solve the assignment/sequencing of time-window orders
   as their own small problem (63 orders × 25 trucks on competitive, worth a more thorough
   search), then insert the non-window orders around them for km and loaded ratio.
4. **Speed:** profile `insert_orders` / candidate generation / `Solution.copy`; ALNS gets only
   a few hundred iterations on competitive.
5. **Benchmark harness** (planned Milestone 3, not built yet): `bench` runs a solver config on
   all snapshots × seeds, prints mean/min/max score and runtime, appends to `results.csv`. A
   change is kept only if bench shows it helps. Run benchmarks one process per core, not 12 at
   once.

### Avoiding overfitting

- Never hardcode trucks/orders or tune parameters on one snapshot/seed.
- Evaluate on all 4 snapshots × seeds, plus unseen data: `solver/make_fake_scenario.py` and new
  snapshots after a server restart (`python -m gruber.cli fetch`, free).
- `missed_orders.py` is a diagnosis tool only; the solver must not read its output.

## 9. Other open items

- **Three loaders exist:** `gruber/loader.py`, `solver/instance.py`, `data_layer/load.py`
  (DuckDB → numpy, alphabetical city order). And three fetch scripts. Should be consolidated,
  or at least adapters written (e.g. `Instance` from `data_layer` by ID).
- `data_layer`'s `results.*` tables (`load.save_run`) could log every solver run for the
  algorithm comparison; not wired up yet.
- `data_layer` prep timing columns ignore breaks (documented as optimistic): fine as heuristics,
  never for feasibility.
- Planned but not built: `cli solve <scenario> --time-limit --seed` writing
  `out/<scenario>/plan.json` and `schedule.json` (per-truck route, arrival/departure, load, for a
  teammate's visualisation) and `cli submit <scenario>` (Validate, local zero-violation assert,
  y/n, then Score). The solver's `run.py` covers part of this.
- Submission on competitive: only 3 Score calls; submit only a plan that the exact simulator
  scores, with zero violations, on a freshly fetched snapshot identical to the server data.
