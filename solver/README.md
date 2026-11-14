# LOGIWISE: Part C, the Solver

Decides **which truck gets each order, where the pickup goes, where the delivery goes**, and keeps rearranging until the score stops improving.

## Run it

Everything at once, from the repo root (data layer → tests → solver):

```bash
./run_all.sh                    # SKIP_FETCH=1 to reuse the current DB; extra args go to run.py
```

Solver only (defaults in [`settings.py`](settings.py), flags override them):

```bash
python run.py                                     # all scenarios from the DuckDB (prep.* tables)
python run.py scenario_big --time 300 --seed 1    # one scenario
python run.py ../data/scenario_big/<ts> --source json            # a JSON folder instead
```

With the DB source, data comes from `instance.load_from_db()`, which builds the same `Instance` as
the JSON loader (checked by `tests/test_from_prep.py`). Both plans are then scored by the verified
simulator (`simulator/simulator.py`) and stored in `results.runs` (`--no-save` to skip).

Outputs in `out/<scenario_id>/` (DB) or `<folder>/out/` (JSON):

| File | What it is |
|---|---|
| `plan_initial.json` | Initial plan in the official submission format (the "before") |
| `plan_optimized.json` | Best ALNS plan, ready for `/Validate` → `/Score` |
| `compare.md` / `.json` | Before vs after, the waterfall of lost points, and why each missed order was missed |
| `history.csv` | Best score over time (convergence chart) |
| `operators.json` | Which ALNS moves found improvements (for the "How it works" tab) |

No dependencies beyond the Python 3.10+ standard library.

## The math (in the order it runs)

1. **Binary decisions.** Each order is either assigned to exactly one truck or not.
2. **Feasibility.** Capacity, truck type, pickup before delivery, time windows (≤ 60 min late), and driver breaks and rests are simulated exactly. Nothing infeasible ever enters a plan.
3. **Marginal score ΔS = S_new − S_old** (the signature idea). For every capacity-feasible insertion position, the truck is re-simulated and the **official score** is recomputed. The highest positive ΔS wins. Because ΔS is the real score, the solver automatically trades km against deliveries, cheap and clean trucks against nearby ones, and empty km against detours, using the jury's own weights.
   - Phase 1 inserts time-window orders by **regret** (orders that fit only one truck go first).
   - Phase 2 inserts everything else. Greedy, regret-2 and regret-3 are all tried; the best becomes the start.
4. **ALNS (Adaptive Large Neighbourhood Search).**
   - Each iteration removes q orders (random / worst / related-Shaw / whole route / around the longest empty legs) and re-inserts them with ΔS (greedy, noisy greedy, regret-2, regret-3).
   - **Simulated annealing** sometimes accepts a slightly worse plan, to escape local optima.
   - Operator weights adapt to what works on this instance.

## Speed tricks (all exact, verified)

- A truck is re-simulated only **from the insertion point onward**, resuming from the saved state. Tested: 9,169 insertions, 0 mismatches against a full simulation.
- Positions are pre-ranked by extra km; only the best few are fully simulated (4× more for time-window orders).
- Insertions are cached per (order, truck); after a move only the changed truck is recomputed.

## Time rules (verified against the API)

`evaluator.py` follows the API's behaviour as established in `docs/semantics.md`
(156 Simulate/Score responses reproduced exactly by `simulator/simulator.py`):

- driving minutes = `ceil(km * 60 / 70)` per leg; a break or rest can interrupt a leg;
- time spent standing still (waiting + service, summed over consecutive stops in the same city)
  counts toward the next pause: only `45 - standing` (break) or `660 - standing` (rest) is added,
  and standing >= 45 min before driving resets the 4.5 h counter;
- lateness = arrival - `to`; an order late at both stops counts the larger lateness.

The API's time windows are `pickup_window` / `delivery_window` = `{"from", "to"}` in minutes or `null`.

`tests/test_solver_evaluator.py` checks `simulate_truck` against `simulator.simulator` on random
routes from the saved snapshots (km, cost, CO2, finish time, driving, breaks, value) and checks
that resuming from a saved state equals a full simulation. Run `python -m pytest -q tests`.

`MAX_FINISH_MIN` (off by default) caps route length for a more realistic demo. The official score has no planning horizon, so the score-maximizing plan can give one truck a very long route.

## Results on fake data (60 s ALNS each)

| Scenario | Initial | Optimized | Orders |
|---|---:|---:|---:|
| small | 910.2 | 979.8 | 20/20 |
| middle | 962.3 | 997.9 | 50/50 |
| big | 935.0 | 953.5 | 112/120 |
| competitive | 875.4 | 885.2 | 164/200 |

On the fake competitive scenario, 32 of 60 time-window orders can be reached on time by only one truck, and several share that truck. That caps fulfillment; it's a property of the data, not of the solver.
