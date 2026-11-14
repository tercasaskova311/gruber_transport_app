# team-5 · Logi-Wise

Gruber Logistics hackathon 2026. Truck plan solver, local copy of the official simulator, and a dashboard.
Rules and team workflow: see `CLAUDE.md`.

## Calling the Gruber API

**scenario_competitive allows only 3 Simulate + 3 Score calls per team, in total.**
small, middle and big have no limit: always test there first.
Validate is free on every scenario. Submit only with `python3 -m simulator.cli submit` (section 3).

### 1. Once: the API key

Create `.env` in the repo root. It is git-ignored: **never commit it or paste the key anywhere else.**

```bash
cat > .env          # paste the two lines below, press Enter, then Ctrl+D
```
```
GRUBER_BASE_URL=https://hackathon-challenge.gruber-logistics.dev/Hackaton2026
GRUBER_API_KEY=<your key>
```
Check (shows the names only, not the key): `grep -o '^[A-Z_]*=' .env` must print both names.

### 2. Get a plan

Either solve now and keep the best of several runs (no API calls; about 5-10 minutes):

```bash
python3 -m tools.portfolio data/scenario_big/<snapshot> --time 300 --out out/submit/big --save-db
# plan: out/submit/big/best_plan.json     (--save-db also stores it in results.runs)
```

or take the best plan already stored in the database:

```bash
mkdir -p out/submit
python3 - <<'EOF'
import duckdb
c = duckdb.connect("data/hackathon.duckdb", read_only=True)
for sid in ("scenario_big", "scenario_competitive"):
    run_id, score, plan = c.execute(
        "SELECT run_id, score, plan_json FROM results.runs WHERE scenario_id = ? AND n_violations = 0 "
        "ORDER BY score DESC LIMIT 1", [sid]).fetchone()
    open(f"out/submit/plan_{sid.split('_')[1]}.json", "w").write(plan)
    print(sid, run_id, round(score, 2))
EOF
```

`out/` is git-ignored. On Windows use `python` instead of `python3`.

### 3. Submit: always through `simulator.cli submit`

Do not call `Client().simulate()` / `Client().score()` by hand. The submit command runs every
free check first and makes at most **one** Score call:

1. downloads the scenario again and compares it with the snapshot the plan was built on
   (if the server restarted, it saves the new data and stops: solve again on it);
2. scores the plan with the local simulator and requires 0 violations;
3. calls the free API Validate and requires 0 violations there too;
4. shows the Score calls recorded in `out/submissions/log.csv`;
5. asks `Send to Score? [y/N]`;
6. sends the plan, saves the response in `out/submissions/<scenario>/`, appends to the log, stores
   the response in `results.runs` (`source = score`) and compares the API score with the local one.

```bash
# rehearsal: steps 1-4 only, nothing is sent to Score. Run it as often as you like.
python3 -m simulator.cli submit scenario_big out/submit/big/best_plan.json --dry-run

# real submission (small, middle, big: no limit)
python3 -m simulator.cli submit scenario_big out/submit/big/best_plan.json
```

OK when the command ends with `API score = local score`. No Simulate call is needed: the local
simulator reproduces the API exactly (checked on 156 responses and on our real submissions).

### 4. scenario_competitive (counts against the 3 Score calls)

The log only counts calls made with this command on
your own computer, and the API does not report how many calls are left
(`GET /Hackaton2026/Team` returns 404).

```bash
# 1. dry run first; go on only if every check passes and the expected score is the one you want
python3 -m simulator.cli submit scenario_competitive out/submit/competitive/best_plan.json --dry-run

# 2. the real call: needs --i-am-sure, then "y", then typing the scenario name
python3 -m simulator.cli submit scenario_competitive out/submit/competitive/best_plan.json --i-am-sure
```

The command refuses when the log already shows 3 Score calls on competitive, and warns when the
exact same plan file was sent before.
Every request and response is also saved in `data/api_responses/`.
