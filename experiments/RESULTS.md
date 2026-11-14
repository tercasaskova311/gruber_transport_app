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
| ejection sweep (config `eject`) | algo/ejection @ 9d2db83 | 1000.00 (0) | 997.11 (-0.03, noise) | 970.51 (**-1.15**, worse) | 924.88 (**+4.97**, at the threshold, all 3 seeds above best's max) | 926.91 (+1.14, noise) | 898.07 (+1.73, noise) | 903.90 (-0.25, noise) | accept: competitive better; the big drop was seed luck (8-seed check below) | **accepted**, merged into best, on by default |
| ejection + blocking destroy (config `eject+block`, 3 scenarios only) | algo/ejection @ 9d2db83 | - | - | 971.05 (-0.61, worse) | 924.18 (+4.27, noise) | - | 897.66 (+1.32, noise) | - | no gain over `eject` alone | kept in code, off |
| **best** after merging ejection (current reference; big = 8 seeds) | best @ cb9aeb5 | 1000.00 | 997.15 | 971.19 (8 seeds: 2 low, 6 high) | 924.50 | 926.85 | 898.02 | 902.30 | reference for the next experiments | - |
| first-leg moves (config `loaded`; reduced benchmark) | algo/loaded @ 7ee2d47 | - | 997.13 (-0.02, noise) | 971.03 (8 seeds: 3 low, 5 high; -0.16, noise) | 923.91 (-0.59, noise) | - | - | 903.71 (+1.41, noise) | reject: no effect | **rejected** (branch kept) |
| time-window skeleton first, hard protection (config `tw-first`) | algo/tw-first @ cec1039 | 1000.00 (0) | 996.39 (**-0.76**, worse) | 971.05 (3 seeds; -0.14, noise) | 928.13 (8 seeds vs 923.39; **+4.74**, real) | 926.74 (-0.11, noise) | 895.56 (8 seeds vs 897.96; **-2.40**, worse) | 905.68 (+3.38, noise) | mixed: do not make default; keep as opt-in config for the portfolio | **accepted as opt-in** (merged, default unchanged) |
| same, soft protection (config `tw-first-soft`, 3 scenarios x 3 seeds) | algo/tw-first @ cec1039 | - | - | 971.11 | 928.10 | - | 896.13 | - | same as hard within noise | merged as config, off |

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

## algo/ejection details (quick budget, config `eject`)

| set | scenario | mean | std | min | max | fulfilled | unserved TW | F | cost | loaded | co2 | iters | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| real | small | 1000.00 | 0.00 | 1000.00 | 1000.00 | 20.0/20 | 0.0 | 100.00 | 100.00 | 100.00 | 100.00 | 22133 | 60 |
| real | middle | 997.11 | 0.02 | 997.09 | 997.13 | 50.0/50 | 0.0 | 100.00 | 100.00 | 98.08 | 100.00 | 6219 | 61 |
| real | big | 970.51 | 1.03 | 969.89 | 971.70 | 115.0/120 | 5.0 | 94.48 | 100.00 | 98.73 | 100.00 | 783 | 63 |
| real | competitive | 924.88 | 0.37 | 924.55 | 925.27 | 177.0/200 | 23.0 | 85.28 | 100.00 | 98.99 | 100.00 | 464 | 71 |
| fake | fake_big_a | 926.91 | 0.00 | 926.91 | 926.91 | 107.0/120 | 13.0 | 85.38 | 100.00 | 100.00 | 100.00 | 431 | 67 |
| fake | fake_comp_a | 898.07 | 0.90 | 897.43 | 899.10 | 168.0/200 | 32.0 | 79.79 | 100.00 | 99.40 | 100.00 | 285 | 80 |
| fake | fake_comp_b | 903.90 | 4.01 | 899.52 | 907.40 | 172.0/200 | 28.0 | 81.21 | 100.00 | 98.57 | 100.00 | 330 | 77 |

Ejection moves applied per run: competitive 16-21 (12-15 s of the 60 s), fake_comp 13-31
(10-16 s), fake_big_a 10-16 (4-7 s), big 1-2 (1 s), middle and small 0.

Side finding (diagnostic, not a proven bound): solving ONLY the time-window orders with a
value-only objective, the same ALNS serves 41 of 63 on competitive (full plans: 39-40), 15 of 20
on big (full plans: 15) and 29 of 60 on fake_comp_a (full plans: 28). The plans are probably
close to the number of time-window orders that can be served at all.

## Big is bimodal (8 seeds, 60 s, algo/ejection @ eb63cd4)

Runs on big end on one of two plateaus, about 969.9 or about 971.6 (same 115 orders, different
empty km), with or without ejection:

| config | mean | std | min | max | runs on the low plateau |
|---|---|---|---|---|---|
| default | 970.98 | 0.88 | 969.87 | 971.69 | 3 of 8 (seeds 1, 5, 6) |
| eject | 971.00 | 0.86 | 969.83 | 971.71 | 3 of 8 (seeds 1, 3, 4) |

So the earlier "big -1.15" for ejection was luck, and so was the 6-of-6 high plateau of `best`.
**Corrected threshold for big: 1.5** with 3 seeds (not 0.5); for a firm answer on big use 8 seeds.
A fair 3-seed reference for big is about 971.0, not 971.66.

## algo/loaded findings

- All empty km in the plans are first legs (truck start -> first pickup); mid-route empty km are 0.
- Applying the first-leg moves to 17 final plans of `best` (big x8, competitive x3, fake_comp_a x3,
  fake_comp_b x3) found 0 improving moves. During runs the sweep applies 1-11 small moves on
  intermediate plans (under 1 s per run), without effect on the final score.
- Checked by hand: middle T02 (284 km empty, 8,000 kg) carries O014 (6,400 kg, pickup window
  405-540); the two orders waiting at its start weigh 2,300 and 5,200 kg and cannot ride along, and
  delivering either first makes O014 465-750 min late. Big T10 (1,295 km empty) is the same story
  with O028. These empty legs are forced by capacity and time windows.
- Middle at about 997.1 therefore looks like the practical optimum for this snapshot.

## algo/tw-first details (quick budget)

Reference = `best` (default config) with the same seeds; competitive and fake_comp_a use 8 seeds.

| set | scenario | seeds | best mean (std) | tw-first mean (std) | min | max | delta | fulfilled best -> tw-first | unserved TW | loaded best -> tw-first |
|---|---|---|---|---|---|---|---|---|---|---|
| real | small | 3 | 1000.00 (0.00) | 1000.00 (0.00) | 1000.00 | 1000.00 | 0 | 20 -> 20 | 0 | 100.00 -> 100.00 |
| real | middle | 3 | 997.15 (0.05) | 996.39 (0.03) | 996.36 | 996.42 | -0.76 | 50 -> 50 | 0 | 98.10 -> 97.59 |
| real | big | 8 / 3 | 971.19 (0.74) | 971.05 (1.02) | 969.87 | 971.68 | -0.14 | 115 -> 115 | 5.0 | 99.25 -> 99.09 |
| real | competitive | 8 | 923.39 (1.99) | 928.13 (2.63) | 925.11 | 931.83 | +4.74 | 176.8 -> 177.9 | 23.2 -> 22.1 | 98.78 -> 98.85 |
| fake | fake_big_a | 3 | 926.85 (0.10) | 926.74 (0.00) | 926.74 | 926.75 | -0.11 | 107 -> 107 | 13.0 | 99.96 -> 99.89 |
| fake | fake_comp_a | 8 | 897.96 (0.68) | 895.56 (2.20) | 893.05 | 898.68 | -2.40 | 167.9 -> 167.5 | 32.1 -> 32.5 | 99.51 -> 99.33 |
| fake | fake_comp_b | 3 | 902.30 (1.80) | 905.68 (1.20) | 904.98 | 907.07 | +3.38 | 171.7 -> 173.0 | 28.3 -> 27.0 | 98.28 -> 98.48 |

Competitive, 8 seeds: best 919.4-924.9, tw-first 925.1-931.8 (every tw-first seed above every
best seed). Best single plan so far on competitive: 931.83 (179/200).
