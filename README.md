# team-5 · Logi-Wise

Gruber Logistics hackathon 2026. Truck plan solver, local copy of the official simulator, and a dashboard.
Rules and team workflow: see `CLAUDE.md`.

## How the solver works

### The problem

We get a list of orders (pick up here, deliver there), a fleet of trucks, and the distances
between cities. We decide which truck carries which order and in what sequence it makes its stops.
A plan scores up to 1000 points:

- half of the score is how much order value gets delivered;
- the other half is low cost, low CO2 and few empty kilometres.

Trucks differ in size and type (standard, refrigerated, hazardous goods), drivers must take breaks,
and some orders have a time window: more than 60 minutes late and the order does not count.

There are far too many possible plans to try them all, so we improve a plan step by step.

### The base: destroy and repair (ALNS)

1. **Build a first plan.** Add the orders one at a time, each at the place where it raises the
   score the most. Orders with a time window go first.
2. **Destroy.** Take a few orders out of the plan (5 % to 30 % of them). Several rules choose
   which: random ones, the ones that add little, ones close to each other, a whole truck, or the
   ones next to a long empty drive.
3. **Repair.** Put them back, each at its best place.
4. **Keep or discard.** A better plan is kept. A slightly worse one is sometimes kept too,
   often at the start and rarely at the end, so the search does not get stuck too early.
5. **Learn.** Rules that found improvements are picked more often.
6. Repeat steps 2 to 5 until the time is up, then return the best plan seen.

This method is called Adaptive Large Neighbourhood Search (ALNS). One thing is special in our
version: every decision is judged by the **real score**. We wrote an exact copy of the official
simulator (it matches the API on 156 test plans, to the last digit), so the solver never works
with an estimate.

### What we added on top

Each add-on was kept only if it helped across all our test data (the 4 official scenarios plus
3 that we generated ourselves) and several random starts. The numbers are for the largest
scenario, `competitive` (200 orders, 25 trucks), averaged over runs of 60 seconds.

| Step | What it does | Score |
|---|---|---|
| First plan only | step 1 above, no improvement loop | 908 |
| Base ALNS | the destroy and repair loop | 916 |
| + Speed | the same search with less repeated work, so 1.5 to 2 times more steps in the same time | 920 |
| + Making room | for an order that is left out: take one or two orders off a truck that could reach it in time, put the left-out order in, and find new places for the ones taken off | 925 |
| + Time windows first | plan only the time-window orders first, as their own small puzzle, then fit all other orders around them and do not move them again | 928 |
| + Several runs | run the normal version and the time-windows-first version side by side with different random starts, for 5 minutes each, and keep the best plan | 932.22 |
| + Polishing | take the finished plan and try thousands of tiny changes (move 1 to 3 orders to a better place), keeping only the ones that raise the score; this removes some empty kilometres | **932.26** |

"Time windows first" helps on some data and hurts on other data, so it is not the default.
Running both versions and keeping the better plan gets the gain without the risk.

### What we tried that did not help

- **Reducing empty first drives.** The empty kilometres that remain are forced by truck size and
  time windows.
- **Removing whole stretches of neighbouring routes at once** (the SISR method). Same score.
- **Changing how much is destroyed, and restarting when stuck.** Smaller steps after a success, larger
  ones when nothing improves, and a restart from the best plan after a long quiet period. Same score.
- **Mixing routes from different plans.** The orders that only some plans deliver all need the same
  truck at the same hour, so the best mix is no better than the best single plan.

Many different plans end at the same score and leave out the same orders. We also searched the
time-window orders on their own, for 4 minutes and with three different search styles: every run
stops at the same 42 of 63. For this data we believe we are close to the best score that can be
reached; what polishing still finds is in the second decimal.

### Scores confirmed by the official API

| Scenario | Orders | Delivered | Score |
|---|---|---|---|
| small | 20 | 20 | 1000.00 |
| middle | 50 | 50 | 997.28 |
| big | 120 | 115 | 971.77 |
| competitive | 200 | 179 | 932.26 |

Every submission came back with exactly the score our local simulator predicted.
All plans have zero rule violations. Measurements behind this section: `experiments/RESULTS.md`.
Technical details: `solver/README.md`.

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

Optional last step, to gain a few hundredths: polish the plan (no API calls, plan must be for this snapshot):

```bash
python3 -m tools.polish data/scenario_big/<snapshot> out/submit/big/best_plan.json --time 300 --out out/submit/big/polished.json
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
