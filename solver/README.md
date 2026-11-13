# LOGIWISE: Part C, the Solver

Decides **which truck gets each order, where the pickup goes, where the delivery goes**, and keeps rearranging until the score stops improving.

## Run it

```bash
python make_fake_scenario.py --preset competitive --out data/fake_competitive   # offline test data
python run.py data/fake_competitive --time 300                                    # build → optimize → compare
```

For real data, save each API response into a folder (`cities.json`, `trucks.json`, `orders.json`, `distance_matrix.json`) and run `python run.py <that folder>`.

Outputs in `<folder>/out/`:

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

## Swapping in Part B's simulator

The solver only calls `simulate_truck(...)` and `score(...)` from `evaluator.py`. Once B's `sim.py` matches the API, either make its rules identical to `evaluator.py`, or wrap B's functions with the same signatures.

## ⚠ Assumptions to test against `/Simulate` (top of `evaluator.py`)

| Flag | Current guess |
|---|---|
| `CEIL_PER_LEG` | `ceil` applied to each leg's driving minutes |
| `BREAKS_MID_LEG` | a break or rest can interrupt a long drive |
| `WAIT_PLUS_SERVICE_COUNTS` | waiting + service ≥ 45 min resets the 4.5 h counter |
| `LATENESS_AT_ARRIVAL` | lateness measured on arrival |
| `GENERIC_WINDOW_APPLIES_TO` (in `instance.py`) | a plain `time_window` field applies to the delivery |

Time-window field names in the real JSON are unknown. `instance.py` accepts several shapes and fails loudly if it can't parse one.

`MAX_FINISH_MIN` (off by default) caps route length for a more realistic demo. The official score has no planning horizon, so the score-maximizing plan can give one truck a very long route.

## Results on fake data (60 s ALNS each)

| Scenario | Initial | Optimized | Orders |
|---|---:|---:|---:|
| small | 910.2 | 979.8 | 20/20 |
| middle | 962.3 | 997.9 | 50/50 |
| big | 935.0 | 953.5 | 112/120 |
| competitive | 875.4 | 885.2 | 164/200 |

On the fake competitive scenario, 32 of 60 time-window orders can be reached on time by only one truck, and several share that truck. That caps fulfillment; it's a property of the data, not of the solver.
