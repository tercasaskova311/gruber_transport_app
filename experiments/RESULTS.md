# Experiment leaderboard

Scores are from the exact local simulator (`gruber/simulator.py`), 0 violations in every run.
Raw rows: `experiments/results.csv`. Reprint any run: `python -m tools.bench --show --time 60`.

Budgets: **quick** = 60 s ALNS x seeds 1,2,3, 2 processes at once (4-core laptop).
**full** = 300 s x 3 seeds, only on request.

## Noise (baseline, quick budget)

Std across 3 seeds: small 0, middle 0.04, big 0.19, competitive 3.10, fake_big_a 0.00,
fake_comp_a 0.79, fake_comp_b 2.74. With 3 seeds per side, a difference between two means
counts as real only above roughly:

| scenario | real difference if larger than |
|---|---|
| small, middle | 0.1 |
| big, fake_big_a | 0.5 |
| competitive, fake_comp_a, fake_comp_b | 5 |

(About 2 standard errors of a difference of two 3-seed means; for the competitive-size
scenarios the largest observed std, 3.1, is used for all three.)

## Leaderboard (quick budget, mean of 3 seeds; delta vs `best` at the time)

| experiment | branch @ sha | small | middle | big | competitive | fake_big_a | fake_comp_a | fake_comp_b | verdict | decision |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | bench @ d3c8304 | 1000.00 | 997.13 | 969.85 | 916.00 | 923.47 | 895.81 | 901.74 | reference | - |
| speed (same search, 1.5-2x more iterations) | algo/speed @ 61f4814 | 1000.00 (0) | 997.11 (-0.02, noise) | 971.59 (**+1.74**) | 919.16 (+3.16, noise) | 926.87 (**+3.40**) | 897.21 (+1.40, noise) | 903.44 (+1.70, noise) | accept as infrastructure: nothing worse, big and fake_big_a better beyond noise, competitive up but within noise | **accepted**, merged into best |
| **best** after merging speed (re-run, current reference) | best @ 0fd3103 | 1000.00 | 997.14 | 971.66 | 919.91 | 925.77 | 896.34 | 904.15 | reference for the next experiments | - |

Note: runs are time-limited, so the same code and seeds do not repeat exactly (compare the two
rows above: same code, competitive 919.16 vs 919.91, fake_big_a 926.87 vs 925.77 with one seed
back at 923.47). The fake_big_a threshold is therefore raised from 0.5 to 3.

## Baseline details

| set | scenario | mean | std | min | max | fulfilled | unserved TW | F | cost | loaded | co2 | iters | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| real | small | 1000.00 | 0.00 | 1000.00 | 1000.00 | 20.0/20 | 0.0 | 100.00 | 100.00 | 100.00 | 100.00 | 14409 | 60 |
| real | middle | 997.13 | 0.04 | 997.09 | 997.17 | 50.0/50 | 0.0 | 100.00 | 100.00 | 98.09 | 100.00 | 4127 | 62 |
| real | big | 969.85 | 0.19 | 969.65 | 970.04 | 115.0/120 | 5.0 | 94.48 | 100.00 | 98.29 | 100.00 | 501 | 67 |
| real | competitive | 916.00 | 3.10 | 913.18 | 919.32 | 174.3/200 | 25.7 | 83.41 | 100.00 | 99.29 | 100.00 | 446 | 77 |
| fake | fake_big_a | 923.47 | 0.00 | 923.47 | 923.47 | 106.0/120 | 14.0 | 84.69 | 100.00 | 100.00 | 100.00 | 281 | 67 |
| fake | fake_comp_a | 895.81 | 0.79 | 894.98 | 896.54 | 167.7/200 | 32.3 | 79.26 | 100.00 | 99.67 | 100.00 | 177 | 95 |
| fake | fake_comp_b | 901.74 | 2.74 | 898.63 | 903.80 | 171.3/200 | 28.7 | 80.87 | 100.00 | 98.25 | 100.00 | 209 | 88 |

Every unserved order in every run has a time window. "wall s" includes building the start
plan (7 to 35 s on the large scenarios), which is not counted in the 60 s.

## algo/speed details (quick budget)

| set | scenario | mean | std | min | max | fulfilled | unserved TW | F | cost | loaded | co2 | iters | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| real | small | 1000.00 | 0.00 | 1000.00 | 1000.00 | 20.0/20 | 0.0 | 100.00 | 100.00 | 100.00 | 100.00 | 22670 | 60 |
| real | middle | 997.11 | 0.02 | 997.10 | 997.13 | 50.0/50 | 0.0 | 100.00 | 100.00 | 98.07 | 100.00 | 6268 | 61 |
| real | big | 971.59 | 0.02 | 971.57 | 971.62 | 115.0/120 | 5.0 | 94.48 | 100.00 | 99.45 | 100.00 | 878 | 63 |
| real | competitive | 919.16 | 3.51 | 915.46 | 922.44 | 175.3/200 | 24.7 | 84.11 | 100.00 | 99.09 | 100.00 | 682 | 71 |
| fake | fake_big_a | 926.87 | 0.08 | 926.78 | 926.91 | 107.0/120 | 13.0 | 85.38 | 100.00 | 99.97 | 100.00 | 432 | 65 |
| fake | fake_comp_a | 897.21 | 1.28 | 896.29 | 898.68 | 168.0/200 | 32.0 | 79.61 | 100.00 | 99.43 | 100.00 | 348 | 80 |
| fake | fake_comp_b | 903.44 | 3.19 | 899.95 | 906.21 | 171.7/200 | 28.3 | 81.10 | 100.00 | 98.63 | 100.00 | 428 | 75 |

Iterations vs baseline: small 1.57x, middle 1.52x, big 1.75x, competitive 1.53x, fake_big_a 1.54x,
fake_comp_a 1.97x, fake_comp_b 2.05x. Fixed-work check (`python -m tools.speedcheck`): 40 ALNS
iterations on competitive took 5.4 s before and 3.3 s after, with the same resulting score.
