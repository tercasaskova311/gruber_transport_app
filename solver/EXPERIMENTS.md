# Experiments

## How the score works

```
score = 10 × (0.50 × F + 0.20 × C + 0.15 × L + 0.15 × E) − 20 × violations      (max 1000)
```

- **F**: how much of the order value we deliver (in %)
- **C**: cost efficiency (max 100)
- **L**: % of km driven with goods on board
- **E**: CO₂ efficiency (max 100)

Score any plan on your laptop, exactly like the jury:

```bash
python -m gruber.cli local scenario_competitive solver/out/scenario_competitive/plan_optimized.json
```

## Why C and E are always 100

The jury compares our cost with a **pretend plan**:

> Every order gets **its own trip**, straight from pickup to delivery, on the **cheapest truck**.

Our real plan is smarter: **one truck carries several orders at the same time.**
If 3 orders go Vienna → Brussels, the pretend plan drives that road 3 times. We drive it once.

So we drive far fewer km than the pretend plan (25–32 % fewer), and we spend less money and make
less CO₂ than it does. Beating the pretend plan gives **100**, the maximum. Beating it by more
gives nothing extra.

Real numbers (competitive):

| | Pretend plan | Our plan |
|---|---:|---:|
| km | 221,723 | 167,247 |
| cost | €237,243 | €236,733 → **C = 100** |
| CO₂ | 175,161 kg | 154,509 kg → **E = 100** |

Our cost is *just* under the pretend plan's. That's on purpose: the solver uses the leftover money
to deliver more orders and stops right before C would drop below 100.

**What this means for us:** C and E are maxed and L is ~99 %. The only way to gain points is
**F: deliver more orders.** One more order ≈ +3 points in competitive.

## What an experiment is

- **A** = the solver as it is now.
- **B** = the same solver with **one** change.
- Run both with the **same scenarios, same seeds, same time**, one after another.
- B wins if it is better on **at least 4 of 5 seeds** and breaks nothing (0 violations, no fewer orders).

Why 5 seeds? Luck (the random seed) alone moves the score by up to 2 points. One run proves nothing.

## Experiment ab1 (14 Nov 2026)

| | The one change |
|---|---|
| **A · baseline** | nothing |
| **B1 · route7d** | no truck route longer than 7 days |
| **B2 · prune** | skip trucks that can never reach an order in time |

Scenarios big and competitive, seeds 0–4, 20 seconds each, 30 runs, all valid.

| Average of 5 seeds | big | competitive |
|---|---|---|
| A · baseline | 970.48 | 910.48 |
| B2 · prune | 970.38 (same) | **913.84 (+3.35, better on 5/5)** |
| B1 · route7d | 832.48 (−138) | 854.45 (−56) |

**prune ✅ keep it.** The solver stops wasting time on impossible trucks, searches more in the
same time, and delivers about one more order on competitive.

**route7d ❌ not for the submission.** Short routes mean many orders don't get delivered.
Good for the pitch: *"max score" vs "a plan a dispatcher could run this week"*.

## Where the missing points are

Our best plan misses **25 of 200 orders**, about **80 points**. **All 25 have a time window.**

- 3 are almost impossible: at most one truck can get there in time.
- 22 are **timing conflicts**: some truck could do them, but in our plan it's busy elsewhere at that moment.

Next experiments should fix the timing conflicts: plan the hardest orders first (`phase1-order`),
or clear space for a missed order (`make-room`).

## How to run one

```bash
cd solver
python experiment.py --experiment ab1 --variants baseline route7d prune --seeds 0-4 --time 20
python experiment.py --experiment ab1 --report         # show the results again
```

Takes ~15 minutes. Don't run other heavy things meanwhile: it makes the comparison unfair.

## Where results are saved

| What | Where |
|---|---|
| Every scored plan (score, F/C/L/E, orders, km, the plan itself, experiment + seed) | database `data_layer/data/hackathon.duckdb`, table `results.runs` |
| Details per truck and per stop | `results.run_trucks`, `results.run_stops` |
| Latest plan per scenario, ready to submit | `solver/out/<scenario>/plan_optimized.json` |
| Full report with charts | [ab1 report](https://claude.ai/artifact/Kki7FzGG9La9nj1Mr3dJEt) |

The database isn't in git, so everyone has their own copy.
Best plan so far: **921.74** on competitive (176 orders).

```sql
-- best valid plan for a scenario
SELECT run_id, round(score, 2) AS score, orders_fulfilled, plan_json
FROM results.runs
WHERE scenario_id = 'scenario_competitive' AND n_violations = 0
ORDER BY score DESC LIMIT 1;
```
