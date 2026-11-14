# Experiments (A/B testing the solver)

How we decide whether a solver change is an improvement. Code: [`experiment.py`](experiment.py).

## The idea

- **A (control / baseline)** = the solver as it is now.
- **B (variant)** = the same solver with **exactly one change**.
- Everything else is identical: same scenarios, same data snapshot, same seeds, same time budget,
  same machine. So a score difference comes from that one change, not from luck.
- One run proves nothing: the random seed alone moves the score. Measured on `scenario_big`,
  15 s, seeds 0–4, unchanged code: **sd 0.96 points, range 1.85** (969.71 – 971.56).
  So every variant runs on several seeds, and A and B are compared **seed by seed** (paired).

## What "better" means

| | Metric | Rule |
|---|---|---|
| **Main** | Official score (what the jury measures) | higher is better |
| Guardrail | Violations | must be 0 |
| Guardrail | Orders delivered | must not drop |
| Guardrail | Longest truck route (days) | dispatcher realism, target ≤ 7 days (team decision) |
| Guardrail | Runtime | the budget is fixed per experiment |
| Watch | Empty-km %, iterations, late orders | explain *why* the score moved |

**Decision rule.** B replaces A only if:
1. B beats A on at least 4 of 5 seeds (paired), **and**
2. the mean gain is larger than the noise (> ~1 point), **and**
3. no guardrail is broken.

If B loses, write that down too. Then B (if it won) becomes the new baseline for the next experiment.

## How to run

```bash
cd solver
python experiment.py --experiment <name> --variants baseline <variant> [<variant> ...] \
                     --scenarios scenario_big scenario_competitive --seeds 0-4 --time 20
python experiment.py --experiment <name> --report      # comparison table only, from the DB
```

- `--seeds 0-4` or `0,2,5` or `0-2,7`.
- Runs go **one after another**, never in parallel (parallel runs share CPU, and with a time
  budget a slower run does fewer iterations, which looks like a worse algorithm).
- Variants are **interleaved per seed**: baseline s0, B s0, C s0, baseline s1, … so if the laptop
  slows down (heat, other apps), every variant is affected equally.
- Close other heavy programs while it runs. Plug in the laptop.
- Duration ≈ scenarios × seeds × variants × (time + ~5 s). The default set is about 15 minutes.

### What each run does
1. `load_from_db(scenario)`: fresh `Instance` from `prep.*` (latest snapshot).
2. Global switches reset (`evaluator.MAX_FINISH_MIN = None`), then the variant function applies its one change.
3. Start plan: best of greedy, regret-2 and regret-3 insertion.
4. ALNS for `--time` seconds with the given seed.
5. `check_plan`: must have no violations, otherwise the run fails.
6. The plan is scored again by the verified simulator (`gruber/simulator.py`) and saved to
   `results.runs` (+ `run_trucks`, `run_stops`) with `algo = 'alns'` and
   `params_json = {experiment, variant, seed, time_limit_s, iterations, git}`.

### Where results live
Everything is in DuckDB (`data_layer/data/hackathon.duckdb`), so any experiment can be re-reported later:

```sql
SELECT scenario_id, params_json->>'variant' AS variant, params_json->>'seed' AS seed,
       round(score, 2) AS score, orders_fulfilled, n_violations, params_json->>'iterations' AS it
FROM results.runs
WHERE params_json->>'experiment' = 'ab1' AND algo = 'alns'
ORDER BY 1, 2, 3;
```

### Report columns
`n` runs · `mean` / `sd` / `min` / `max` score · `Δ vs A` = mean of the paired (B − A) differences ·
`wins` = seeds where B > A · `orders` = mean delivered · `viol` = max violations ·
`longest` = longest truck route over all runs, in days · `empty%` = empty km / total km · `iters` = mean ALNS iterations.

## Adding a new variant

In `experiment.py`, write one function that makes **one** change to the instance or a switch,
and register it in `VARIANTS`:

```python
def v_my_idea(inst: Instance) -> None:
    """One sentence: what changes and why."""
    ...

VARIANTS = {..., "my_idea": v_my_idea}
```

If the change is inside the solver code (e.g. a new operator), make it switchable by a flag the
variant function sets, so baseline and variant run the same code version. If a variant wins, make
it the default in the solver and remove the flag.

## Known limits

- **Time budget = machine-dependent.** Compare only runs from the same machine (`git` and the
  laptop). A fixed iteration budget would be fairer between machines; ALNS doesn't have one yet.
- **The start plan ignores the seed**: greedy / regret insertion is deterministic (953.07 on big for
  every seed). Only ALNS varies.
- **The data snapshot must be the same** for all runs of an experiment (`results.runs.snapshot_id`).
  If the server restarts mid-experiment, start again.
- 5 seeds is the minimum. For small differences (< 1 point), use 10.

---

## Log

### ab1: route limit and pruning (2026-11-14)

**Setup**

| | |
|---|---|
| Code | `develop` @ `af3bde5` + uncommitted `experiment.py` (`git` = `af3bde5+dirty`) |
| Data | snapshot `20261113T203436220952Z` |
| Machine | MacBook Pro, Intel i5-7360U 2.3 GHz, 4 threads, 8 GB · Python 3.12.2 · DuckDB 1.5.1 |
| Scenarios | `scenario_big` (120 orders, 15 trucks), `scenario_competitive` (200 orders, 25 trucks) |
| Seeds | 0, 1, 2, 3, 4 (paired) |
| Budget | 20 s ALNS per run (+ start-plan construction) |
| Order | sequential, interleaved per seed |
| Command | `python experiment.py --experiment ab1 --variants baseline route7d prune --scenarios scenario_big scenario_competitive --seeds 0-4 --time 20` |

**Variants**

| Variant | One change | Question |
|---|---|---|
| `baseline` (A) | none | reference |
| `route7d` (B1) | `evaluator.MAX_FINISH_MIN = 7 × 24 × 60`: any route ending after day 7 is infeasible | How many points does a realistic plan cost? (today's best competitive plan has a 34-day route) |
| `prune` (B2) | remove (order, truck) pairs with `prep.order_truck_options.alone_fulfillable = false` from `inst.compatible` (822 of 4,104 in competitive) | Is skipping impossible pairs free speed? Exact: `alone_*` times are lower bounds (start at minute 0, drive straight, no breaks), so a removed pair can never be in a valid plan. |

**Results**: *pending (running)*

**Decision**: *pending*
