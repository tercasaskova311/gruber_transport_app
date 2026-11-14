# CLAUDE.md

Team 5, Gruber Logistics hackathon 2026 (LOGIWISE). We build a pickup-and-delivery truck plan
that maximises the official score, plus a demo around it.

## Branches

- `develop`: the integration branch. Solver + simulator + data layer, all tests passing. Start new work here.
- `main`: what we'd submit. `develop` is merged into it when stable.
- Short-lived feature branches off `develop` (e.g. `feature/prep-pruning`), merged back when done.

## Layout

| Path | Part | What it is |
|---|---|---|
| `gruber/` | B, simulator | API client, snapshot loader, **exact local copy of Validate / Simulate / Score** (verified on 156 API responses). The single source of truth for rules. |
| `data_layer/` | A, data | Python package. DuckDB pipeline: `raw.*` (append-only API data), `prep.*` (solver-ready features, rebuilt each run), `results.*` (every scored plan). `load.py` = connect / list_scenarios / save_run. |
| `solver/` | C, solver | Greedy ΔS insertion + ALNS. `instance.py` builds the in-memory `Instance` (from `prep.*` via `load_from_db()`, or from JSON); `settings.py` = run settings; `evaluator.py` must match `gruber/simulator.py`. |
| `run_all.sh` | | One command: data layer → tests → solver. |
| `tools/` | | `parity.py` (local vs saved API responses), `validate_fuzz.py`, `plangen.py` |
| `tests/` | | pytest: simulator parity + solver evaluator |
| `docs/` | | `semantics.md` (**verified API behaviour, read it before changing any rule**), challenge PDF, swagger |
| `data/` | | Snapshots `data/<scenario>/<timestamp>/`, parity cases in `data/parity/` |

## Commands

```bash
pip install -r requirements.txt                    # requests, numpy, pytest
python -m pytest -q tests                          # must pass before any commit
python -m tools.parity compare                     # local simulator vs saved API responses
python -m gruber.cli fetch                         # snapshot all scenarios (free)
python -m gruber.cli local scenario_small plan.json   # local score, no API call
./run_all.sh                                       # data layer -> tests -> solver (SKIP_FETCH=1 to reuse DB)
cd data_layer && ./run_all.sh                      # fetch -> prep tables -> checks
cd solver && python run.py                         # every scenario in the DB -> solver/out/ + results.runs
cd solver && python run.py scenario_big --time 300 # one scenario; --source json <folder> for JSON; --no-save
```

## Data flow

`raw.*` → `prepare.sql` → `prep.*` → `instance.load_from_db()` (one read into Python lists, the
solver never queries DuckDB while solving: a query is ~14,000× slower than a list lookup) →
`construct` + ALNS → plans scored again by `gruber/simulator.py` → `results.runs`.
The JSON loader stays for tests and fake scenarios (fixed data in git); `tests/test_from_prep.py`
checks both loaders build the same problem.

## Hard rules for Claude

- **Never call Simulate or Score on the API without asking first.** `scenario_competitive` allows
  only **3 Simulate + 3 Score calls per team, total**. Never pass `i_am_sure=True` / `--i-am-sure`.
  Validate and the `/Scenarios` GETs are free. Use the local simulator for everything else.
- Never read, print or commit `.env` (holds `GRUBER_API_KEY`).
- Rules live in `gruber/simulator.py` + `docs/semantics.md`. Don't "fix" a rule from the PDF
  if it contradicts them; they were verified against the API. If unsure, add a probe to
  `data/parity`, don't guess.
- Any change to `solver/evaluator.py` or `gruber/simulator.py` must keep `pytest` and
  `tools.parity compare` at zero mismatches.
- `solver/solver.py` and `evaluator.py` stay standard-library only; duckdb is imported only inside
  the DB loading / saving functions.
- In SQL, every join includes `scenario_id` (ids like `C008` repeat across scenarios).
- New `prep` table → add its key to `PREP_KEYS` in `data_layer/checks.py`.
- `data_layer` modules import each other with `try: from . import x / except ImportError: import x`
  so they work both as a package and as scripts. Keep that pattern.
- Work on `develop` or a feature branch off it; don't commit to `main` directly.
  Commit or push only when asked.

## Domain rules (short version; details in `docs/semantics.md`)

- Plan = `{truck_id: [{"action": "pickup"|"delivery", "order": id}, ...]}`. No return to depot.
- Time in minutes from Day 1 06:00. Leg time = `ceil(km*60/70)` per leg; 30 min service per stop.
- Breaks: 45 min after 270 min driving, 11 h rest after 540 min. Can interrupt a leg. Standing time
  (service + waiting) just before counts toward the pause, so often only part of it is inserted.
- Early = wait until window `from`. Late ≤ 60 min: value × (1 − 0.5·late/60). > 60 min: not fulfilled.
  Late at both stops: the max counts.
- Wrong truck type: still loaded and driven, never fulfilled, a violation at every stop.
- Score = 10 × (0.50 F + 0.20 C + 0.15 L + 0.15 E) − 20 × violations
  (F value fulfilled %, C/E cost/CO₂ vs reference from direct km × cheapest/cleanest truck, L loaded km %).
  Plans must have **zero violations**.

## Scenarios

| scenario | cities | trucks | orders | with time window |
|---|---|---|---|---|
| small | 10 | 4 | 20 | 0 % |
| middle | 20 | 8 | 50 | 14 % |
| big | 30 | 15 | 120 | 17 % |
| competitive | 45 | 25 | 200 | 32 % (3+3 API calls only) |

A server restart regenerates all scenarios: re-fetch, then `python -m tools.parity build`.

## Solver approach (decided, don't re-litigate)

Custom ALNS that scores every move with the exact official score. Chosen over VROOM / OR-Tools
because no library models the break and lateness rules or the ratio-based score exactly.
OR-Tools may be added later only as an extra starting solution or a benchmark.
Next steps: use `prep.*` features in the solver, one at a time, measured in `results.runs`:
drop order–truck pairs with `alone_fulfillable = false` (822 of 4,104 in competitive; safe, as
`alone_*` times are lower bounds), phase-1 order by `trucks_on_time` / `planning_order`,
rank trucks by `empty_km_to_pickup`. Then an operator that makes room for unassigned orders.

## Style

- Plain, short explanations; the team mixes languages, so avoid jargon or explain it once.
- Show numbers (score before/after, orders fulfilled) when reporting solver changes.
