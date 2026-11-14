# Logi-Wise · team 5

Gruber Logistics hackathon 2026. A pickup-and-delivery truck planner that maximises the official
score, an exact local copy of the official simulator, and a dashboard for dispatchers and drivers.

Rules, domain details and team workflow: [CLAUDE.md](CLAUDE.md) and [docs/semantics.md](docs/semantics.md).

## Structure

| Folder | What it is |
|---|---|
| `simulator/` | API client and exact local Validate / Simulate / Score (the reference for every rule) |
| `ingestion/` | DuckDB pipeline: `raw.*` API data → `prep.*` solver features → `results.*` scored plans |
| `solver/` | Greedy insertion + ALNS, scored with the exact official score; `explain.py` says why an order is unserved |
| `dashboard/` | Streamlit map: routes on real roads, load on board, unserved orders |
| `tools/` | Parity checks, portfolio runs, benchmarks |
| `tests/` | pytest: simulator parity + solver evaluator |
| `docs/` | Challenge PDF, API docs, verified rules |
| `data/` | `hackathon.duckdb` (git-ignored), scenario snapshots, road shapes, parity cases |

## Setup

```bash
pip install -r requirements.txt
```

Create `.env` in the repo root (git-ignored, **never commit or share it**):

```
GRUBER_BASE_URL=https://hackathon-challenge.gruber-logistics.dev/Hackaton2026
GRUBER_API_KEY=<your key>
```

## Run

```bash
./run_all.sh                                   # fetch data → tests → solver (SKIP_FETCH=1 reuses the DB)
python3 -m pytest -q tests                     # must pass before every commit
cd solver && python3 run.py scenario_big --time 300
python3 -m streamlit run dashboard/app.py      # dashboard, from the repo root
```

None of these call Simulate or Score: all scoring is local.

## Submit a plan

**scenario_competitive allows only 3 Simulate + 3 Score calls per team, in total.** Small, middle
and big have no limit, so test there first. Always submit through `simulator.cli submit`, never by
calling the API client by hand.

1. Get a plan: the best of several solver runs (5–10 min, no API calls):
   ```bash
   python3 -m tools.portfolio data/scenario_big/<snapshot> --time 300 --out out/submit/big --save-db
   ```
2. Dry run: re-downloads the scenario, checks 0 violations locally and on the free Validate,
   shows past Score calls. Nothing is sent.
   ```bash
   python3 -m simulator.cli submit scenario_big out/submit/big/best_plan.json --dry-run
   ```
3. Real submission: asks for confirmation, sends one Score call, logs it to
   `out/submissions/log.csv` and `results.runs`.
   ```bash
   python3 -m simulator.cli submit scenario_big out/submit/big/best_plan.json
   ```
   It is OK when the output ends with `API score = local score`.

For **scenario_competitive**, step 3 also needs `--i-am-sure` and typing the scenario name. The
command refuses after 3 logged Score calls. The log only counts calls made from your own computer,
so agree in the team who submits.
