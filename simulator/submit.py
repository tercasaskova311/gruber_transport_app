"""Guarded submission: every check that can be done for free runs before the one Score call.

  python -m simulator.cli submit <scenario> <plan.json> [--snapshot <dir>] [--dry-run] [--i-am-sure]

Steps, in this order; the first failed step stops the command with a non-zero exit code:
  1. fresh-data check   download the scenario again and compare it with the snapshot the plan
                        was built on (content, not timestamps); if it differs, save the fresh
                        data as a new snapshot and stop
  2. local check        exact simulator on the fresh data; zero violations required
  3. API Validate       free; must be empty and agree with the local validation
  4. remaining calls    team info from the API (if it offers it) + local log of Score calls
  5. confirmation       y/N; scenario_competitive also needs --i-am-sure and the typed name
  6. Score              one call; response and plan copy saved, log line appended; the response is
                        also stored in the team database (results.runs, source=score) if it exists

--dry-run does steps 1-4, prints what step 5 would show, and stops. No Simulate call is ever made.
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path

from . import config, loader, results_db, simulator
from .api import COMPETITIVE, Approval, Client

PARTS = ("cities", "trucks", "orders", "distance_matrix")
LOG_FIELDS = ["time", "scenario", "plan_sha256", "local_score", "api_score"]
COMPONENTS = ("fulfillment", "cost_efficiency", "loaded_ratio", "co2_efficiency", "penalty", "late_penalty")
SCORE_LIMITS = {COMPETITIVE: 3}     # known Score limits per team; other scenarios: no known limit

OK, STOP = 0, 1


def _stdin_ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


# ---------------------------------------------------------------- step 1 helpers
def snapshot_dir(scenario: str, snapshot: str | None, data_dir: Path) -> Path | None:
    if snapshot:
        p = Path(snapshot)
        return p if p.is_dir() else data_dir / scenario / snapshot
    d = data_dir / scenario
    # names: 20261113_192945 (old) or 20261113T203436220952Z (database); sort by the digits, like loader
    key = lambda p: "".join(ch for ch in p.name if ch.isdigit()).ljust(20, "0")
    snaps = sorted((p for p in d.iterdir() if p.is_dir() and (p / "orders.json").exists()), key=key) if d.exists() else []
    return snaps[-1] if snaps else None


def _diff_part(name: str, old, new) -> str | None:
    """One line saying how `new` differs from `old`, or None if the content is identical."""
    if old == new:
        return None
    if name == "distance_matrix" and isinstance(old, dict) and isinstance(new, dict):
        if set(old) != set(new):
            return f"distance matrix changed: different city set ({len(old)} -> {len(new)} cities)"
        n = sum(1 for a in new for b in new[a] if (old[a] or {}).get(b) != new[a][b])
        return f"distance matrix changed: {n} distances differ"
    if isinstance(old, list) and isinstance(new, list):
        key = lambda x: x.get("id") if isinstance(x, dict) else json.dumps(x, sort_keys=True)
        o, n = {key(x): x for x in old}, {key(x): x for x in new}
        added, removed = len(set(n) - set(o)), len(set(o) - set(n))
        changed = sum(1 for k in set(o) & set(n) if o[k] != n[k])
        if not (added or removed or changed):
            return f"{name} changed: same items in a different order"
        return f"{name} changed: {changed} modified, {added} added, {removed} removed (of {len(old)})"
    return f"{name} changed"


def _save_snapshot(scenario: str, fresh: dict, data_dir: Path) -> Path:
    d = data_dir / scenario / time.strftime("%Y%m%d_%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    for name, obj in fresh.items():
        (d / f"{name}.json").write_text(json.dumps(obj, indent=1), encoding="utf-8")
    return d


# ---------------------------------------------------------------- step 4 helpers
def read_log(out_dir: Path) -> list[dict]:
    p = out_dir / "log.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append_log(out_dir: Path, row: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "log.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def _banner(text: str) -> None:
    print("!" * 72)
    for line in text.splitlines():
        print("!! " + line)
    print("!" * 72)


# ---------------------------------------------------------------- the command
def run(scenario: str, plan_path, snapshot: str | None = None, dry_run: bool = False,
        i_am_sure: bool = False, client=None, ask=_stdin_ask,
        data_dir: Path | None = None, out_dir: Path | None = None, save_result=results_db.save) -> int:
    """Run the submission procedure. Returns the process exit code (0 = finished as intended)."""
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    out_dir = Path(out_dir) if out_dir else config.OUT_DIR / "submissions"
    plan_path = Path(plan_path)

    def stop(step: str, msg: str) -> int:
        print(f"\nSTOPPED at {step}: {msg}\nNothing was sent to Score.")
        return STOP

    try:
        raw = plan_path.read_bytes()
        plan = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError) as e:
        return stop("reading the plan", f"cannot read {plan_path}: {e}")
    if not isinstance(plan, dict):
        return stop("reading the plan", "the plan file must be a JSON object {truck id: [stops]}")
    plan_hash = hashlib.sha256(raw).hexdigest()
    client = client or Client()

    # ---- 1. fresh-data check
    print(f"[1/6] Fresh-data check for {scenario}")
    snap = snapshot_dir(scenario, snapshot, data_dir)
    if snap is None or not snap.is_dir():
        return stop("step 1 (fresh data)", f"snapshot not found: {snap or data_dir / scenario}. "
                                           "Fetch the scenario data (ingestion/run_all.sh) and re-run the solver.")
    try:
        fresh = {n: getattr(client, n)(scenario) for n in PARTS}
    except Exception as e:
        return stop("step 1 (fresh data)", f"could not download the scenario: {e}")
    diffs = []
    for n in PARTS:
        f = snap / f"{n}.json"
        if not f.exists():
            diffs.append(f"{n}.json is missing in the snapshot")
            continue
        d = _diff_part(n, json.loads(f.read_text(encoding="utf-8")), fresh[n])
        if d:
            diffs.append(d)
    if diffs:
        new = _save_snapshot(scenario, fresh, data_dir)
        return stop("step 1 (fresh data)",
                    "the server data is not the data this plan was built on (server was restarted?).\n  - "
                    + "\n  - ".join(diffs)
                    + f"\n  compared with snapshot: {snap}\n  fresh data saved as:     {new}\n"
                      f"  Re-run the solver on the new snapshot and submit that plan.")
    print(f"      identical to snapshot {snap.name} (cities, trucks, orders, distance matrix)")

    # ---- 2. local check on the fresh data
    print("[2/6] Local check (exact simulator, fresh data)")
    try:
        sc = loader.from_raw(scenario, *(fresh[n] for n in PARTS))
        local = simulator.score(sc, plan)
    except Exception as e:
        return stop("step 2 (local check)", f"the simulator cannot read this plan: {type(e).__name__}: {e}")
    lr = simulator.api_round(local)         # rounded the way the API returns it
    b, m = lr["breakdown"], lr["metrics"]
    lviol = local["validation"]["violations"]
    print(f"      score            {local['score']:.4f}   (API will show {lr['score']})")
    print(f"      fulfillment      {b['fulfillment']}\n      cost efficiency  {b['cost_efficiency']}\n"
          f"      loaded ratio     {b['loaded_ratio']}\n      CO2 efficiency   {b['co2_efficiency']}")
    print(f"      orders fulfilled {m['orders_fulfilled']}/{m['orders_total']}   "
          f"late {m['orders_late']} (of which too late, not fulfilled: {m['orders_too_late']})")
    if local["_unverified"]:
        _banner("WARNING: this plan relies on a rule the simulator has NOT verified against the API:\n"
                + "\n".join(local["_unverified"]) + "\nThe API score may differ from the local score.")
    if lviol:
        return stop("step 2 (local check)", f"{len(lviol)} violation(s), each costs 20 points:\n  - "
                    + "\n  - ".join(f"{v.get('rule')} {v.get('truck')} {v.get('order')}: {v.get('message')}"
                                    for v in lviol[:10]))
    print("      violations       0")

    # ---- 3. API Validate (free)
    print("[3/6] API Validate (free)")
    try:
        val = client.validate(scenario, plan)
    except Exception as e:
        return stop("step 3 (API Validate)", f"Validate failed: {e}")
    aviol = val.get("violations")
    if aviol or not val.get("is_valid") or aviol is None:
        return stop("step 3 (API Validate)",
                    f"the API reports {len(aviol or [])} violation(s) (is_valid={val.get('is_valid')}) but the local "
                    "check found none: the simulator or the data is out of sync.\n  - "
                    + "\n  - ".join(str(v) for v in (aviol or [])[:10]))
    print("      API: valid, 0 violations (agrees with the local check)")

    # ---- 4. remaining calls
    print("[4/6] Remaining calls")
    try:
        print("      team info from the API: " + json.dumps(client.team()))
    except Exception as e:
        print(f"      team info from the API: not available ({str(e)[:120]}).\n"
              "      The API does not report how many calls are left; only the local log below counts them.")
    log = read_log(out_dir)
    counts: dict[str, int] = {}
    for r in log:
        counts[r["scenario"]] = counts.get(r["scenario"], 0) + 1
    print(f"      Score calls recorded in {out_dir / 'log.csv'}: "
          + (", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none"))
    print("      (only calls made with this command on this computer; teammates' calls are not visible here)")
    used, limit = counts.get(scenario, 0), SCORE_LIMITS.get(scenario)
    same = [r for r in log if r["scenario"] == scenario and r["plan_sha256"] == plan_hash]

    # ---- 5. confirmation
    print("[5/6] Confirmation")
    print("=" * 72)
    print(f"  scenario              {scenario}")
    print(f"  plan file             {plan_path}   (sha256 {plan_hash[:12]})")
    print(f"  expected local score  {lr['score']}")
    print(f"  Score calls used/left {used} recorded here / "
          + (f"{max(limit - used, 0)} left of {limit}" if limit else "no known limit"))
    print("=" * 72)
    if same:
        _banner(f"This exact plan file was already sent to Score on {same[-1]['time']} "
                f"(API score {same[-1]['api_score']}).\nSending it again spends a call for nothing.")
    if limit and used >= limit:
        return stop("step 5 (confirmation)", f"the log already records {used} Score calls on {scenario}; "
                                             f"the limit is {limit}.")
    if dry_run:
        extra = " (plus --i-am-sure and typing the scenario name)" if scenario == COMPETITIVE else ""
        print(f"DRY RUN: all checks passed. A real run would now ask \"Send to Score? [y/N]\"{extra}.\n"
              "Nothing was sent to Score.")
        return OK
    if scenario == COMPETITIVE and not i_am_sure:
        return stop("step 5 (confirmation)", f"{COMPETITIVE} allows only {limit} Score calls in total. "
                                             "Add --i-am-sure if you really want to spend one.")
    if ask("Send to Score? [y/N] ").strip().lower() not in ("y", "yes"):
        return stop("step 5 (confirmation)", "you did not answer y.")
    if scenario == COMPETITIVE:
        if ask(f"This spends 1 of {limit} Score calls. Type the scenario name to confirm: ").strip() != scenario:
            return stop("step 5 (confirmation)", "the scenario name did not match.")

    # ---- 6. Score (the only paid call in this command)
    print("[6/6] Score")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    sub = out_dir / scenario
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"{stamp}_plan.json").write_bytes(raw)
    row = dict(time=now, scenario=scenario, plan_sha256=plan_hash, local_score=lr["score"])
    try:
        resp = client.score(scenario, plan, approval=Approval(scenario, frozenset({"Score"}), 1, i_am_sure))
    except Exception as e:
        _append_log(out_dir, dict(row, api_score=f"ERROR {type(e).__name__}"))
        _banner(f"The Score request failed: {e}\nThe server MAY have counted this call. It is recorded in the "
                "log as used.\nDo not simply retry: check first.")
        return STOP
    (sub / f"{stamp}_score.json").write_text(json.dumps(resp, indent=1), encoding="utf-8")
    _append_log(out_dir, dict(row, api_score=resp.get("score")))
    print(f"      response saved to {sub / f'{stamp}_score.json'} (plan copy next to it)")
    if save_result is not None:             # team database, for the dashboard; never fatal
        try:
            _, msg = save_result(scenario, snap.name, plan, resp, algo="submit", source="score",
                                 params={"plan_file": str(plan_path), "plan_sha256": plan_hash,
                                         "local_score": lr["score"]})
        except Exception as e:
            msg = f"not saved to the database ({type(e).__name__}: {e})"
        print("      " + msg)

    ab = resp.get("breakdown") or {}
    lines = [("score", resp.get("score"), lr["score"])] + [(c, ab.get(c), b.get(c)) for c in COMPONENTS]
    am = resp.get("metrics") or {}
    lines.append(("orders_fulfilled", am.get("orders_fulfilled"), m["orders_fulfilled"]))
    differ = False
    print(f"      {'':18}{'API':>10} {'local':>10} {'diff':>8}")
    for name, a, l in lines:
        if isinstance(a, (int, float)) and isinstance(l, (int, float)):
            d = round(a - l, 4)
            differ |= d != 0
            print(f"      {name:18}{a:>10} {l:>10} {d:>+8.2f}")
        else:
            differ = True
            print(f"      {name:18}{a!s:>10} {l!s:>10} {'?':>8}")
    if differ:
        _banner("API SCORE AND LOCAL SCORE DIFFER.\nThe simulator or the data is out of sync with the server. "
                "Do not trust further local scores\nuntil this is explained (compare the saved response "
                "with `python -m simulator.cli local`).")
    else:
        print(f"      API score = local score = {resp.get('score')}: simulator and data are in sync.")
    return OK
