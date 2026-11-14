# team-5 · Logi-Wise

Gruber Logistics hackathon 2026. Truck plan solver, local copy of the official simulator, and a dashboard.
Rules and team workflow: see `CLAUDE.md`.

## Calling the Gruber API

**scenario_competitive allows only 3 Simulate + 3 Score calls per team, in total.**
small, middle and big have no limit: always test there first.
Validate is free on every scenario.

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

### 2. Get the best plan from the database

```bash
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
(Run `mkdir -p out/submit` first if the folder is missing. `out/` is git-ignored.)

### 3. Rehearsal on scenario_big (no limit)

```bash
# local score, no API
python3 -m simulator.cli local    scenario_big out/submit/plan_big.json
# free API check: both lines must say True
python3 -m simulator.cli validate scenario_big out/submit/plan_big.json
# Simulate: shows the plan and asks y/N before sending
python3 -c "
import json; from simulator.api import Client
r = Client().simulate('scenario_big', json.load(open('out/submit/plan_big.json')))
print('API score:', r.get('score'))"
```
OK when the API score equals the local score. In the y/N screen, trucks must be T01–T15 for big.

### 4. scenario_competitive (counts against the 3 + 3)

Only after step 3 worked, and after:
- `local` and `validate` on `out/submit/plan_competitive.json` show **0 violations** and **True / True**;
- the plan comes from the newest solver run (re-run step 2 after solving);
- if Validate complains about unknown orders or trucks, the server data changed: re-fetch
  (`cd inference && ./run_all.sh`), solve again, then come back.

```bash
python3 -c "
import json; from simulator.api import Client
r = Client().simulate('scenario_competitive', json.load(open('out/submit/plan_competitive.json')), i_am_sure=True)
print('API score:', r.get('score'))"
```
Check that the y/N screen shows trucks up to T25 (competitive), then answer `y`.
For the official submission use `.score(` instead of `.simulate(` (also 3 calls only).
Every request and response is saved in `data/api_responses/`.
