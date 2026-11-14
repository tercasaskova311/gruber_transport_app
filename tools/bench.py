"""Benchmark a solver configuration: every snapshot x seed, scored by the exact simulator.

  python -m tools.bench --config default --time 60 --seeds 1,2,3 [--cores N]
                        [--scenarios big,competitive,fake_comp_a] [--note "text"]
  python -m tools.bench --show [--time 60]        # leaderboard from experiments/results.csv

Each job is `python solver/run.py <snapshot_dir> --time T --seed S --config C --out <dir>`,
at most --cores at once (default: CPU count - 2). Nothing else heavy should run meanwhile:
the solver is time-limited, so a busy machine means fewer iterations and a lower score.

The final plan of every job is scored with gruber.simulator (the exact copy of the API);
any rule violation aborts the benchmark. One row per job is appended to
experiments/results.csv. Plans and logs go to out/bench/ (git-ignored).

Test set:            data/scenario_*/<snapshot>/   (real API snapshots)
Generalization set:  data/fake/*/                  (tools/make_fakes.py; never tune on these)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from simulator import loader, simulator

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "experiments" / "results.csv"
FIELDS = ["when", "branch", "sha", "dirty", "config", "set", "scenario", "snapshot", "seed", "time",
          "score", "fulfillment", "cost_eff", "loaded_ratio", "co2_eff", "fulfilled", "orders",
          "value_fulfilled", "value_total", "unserved_tw", "violations", "iterations", "wall_s",
          "solver_score", "note"]


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def scenarios() -> list[tuple[str, str, str, Path]]:
    """(set, name, snapshot, folder) for every benchmark instance."""
    out = []
    for d in sorted((ROOT / "data").glob("scenario_*")):
        if d.is_dir():
            for snap in loader.list_snapshots(d.name):
                out.append(("real", d.name.replace("scenario_", ""), snap.name, snap))
    fake = ROOT / "data" / "fake"
    if fake.exists():
        for d in sorted(fake.iterdir()):
            if (d / "orders.json").exists():
                out.append(("fake", d.name, "", d))
    return out


def load_dir(name: str, folder: Path):
    rd = lambda n: json.loads((folder / f"{n}.json").read_text(encoding="utf-8"))
    return loader.from_raw(name, rd("cities"), rd("trucks"), rd("orders"), rd("distance_matrix"))


def run_job(job: dict) -> dict:
    out = job["out"]
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "solver" / "run.py"), str(job["folder"]), "--time", str(job["time"]),
           "--seed", str(job["seed"]), "--config", job["config"], "--out", str(out), "--quiet"]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    wall = time.time() - t0
    (out / "stdout.txt").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"solver failed on {job['scenario']} seed {job['seed']}:\n{p.stderr[-2000:]}")
    plan = json.loads((out / "plan_optimized.json").read_text(encoding="utf-8"))
    res = json.loads((out / "result.json").read_text(encoding="utf-8"))
    sc = load_dir(job["scenario"], job["folder"])
    sim = simulator.simulate(sc, plan)
    r = simulator.score(sc, plan, sim)
    m, b = r["metrics"], r["breakdown"]
    ful = sim["_fulfilled"]
    nviol = len(r["validation"]["violations"])
    assert nviol == 0, f"{job['scenario']} seed {job['seed']}: {r['validation']['violations'][:5]}"
    assert not r["_unverified"], f"{job['scenario']}: plan uses unverified rule {r['_unverified']}"
    # the solver's own evaluator must agree with the exact simulator
    assert abs(res["score"] - r["score"]) < 1e-6, (job["scenario"], job["seed"], res["score"], r["score"])
    return dict(set=job["set"], scenario=job["scenario"], snapshot=job["snapshot"], seed=job["seed"],
                time=job["time"], config=job["config"], score=round(r["score"], 4),
                fulfillment=round(b["fulfillment"], 4), cost_eff=round(b["cost_efficiency"], 4),
                loaded_ratio=round(b["loaded_ratio"], 4), co2_eff=round(b["co2_efficiency"], 4),
                fulfilled=m["orders_fulfilled"], orders=m["orders_total"],
                value_fulfilled=round(m["value_fulfilled"], 4), value_total=m["value_total"],
                unserved_tw=sum(1 for o in sc.orders if o.id not in ful and (o.pw or o.dw)),
                violations=nviol, iterations=res["iterations"], wall_s=round(wall, 1),
                solver_score=round(res["score"], 4))


def summarize(rows: list[dict]) -> list[dict]:
    g = defaultdict(list)
    for r in rows:
        g[(r["set"], r["scenario"], r["snapshot"])].append(r)
    out = []
    for (st, name, snap), rs in g.items():
        s = [float(r["score"]) for r in rs]
        mean = lambda k: statistics.mean(float(r[k]) for r in rs)
        out.append(dict(set=st, scenario=name, snapshot=snap, n=len(s), mean=statistics.mean(s),
                        std=statistics.stdev(s) if len(s) > 1 else 0.0, min=min(s), max=max(s),
                        fulfilled=mean("fulfilled"), orders=int(float(rs[0]["orders"])),
                        unserved_tw=mean("unserved_tw"), F=mean("fulfillment"), cost=mean("cost_eff"),
                        loaded=mean("loaded_ratio"), co2=mean("co2_eff"), iters=mean("iterations"),
                        wall=mean("wall_s")))
    return out


def print_summary(summ: list[dict], md: bool = False) -> None:
    head = ["set", "scenario", "n", "mean", "std", "min", "max", "fulfilled", "unserved TW", "F",
            "cost", "loaded", "co2", "iters", "wall s"]
    lines = []
    for s in summ:
        lines.append([s["set"], s["scenario"], str(s["n"]), f"{s['mean']:.2f}", f"{s['std']:.2f}",
                      f"{s['min']:.2f}", f"{s['max']:.2f}", f"{s['fulfilled']:.1f}/{s['orders']}",
                      f"{s['unserved_tw']:.1f}", f"{s['F']:.2f}", f"{s['cost']:.2f}", f"{s['loaded']:.2f}",
                      f"{s['co2']:.2f}", f"{s['iters']:.0f}", f"{s['wall']:.0f}"])
    if md:
        print("| " + " | ".join(head) + " |")
        print("|" + "---|" * len(head))
        for l in lines:
            print("| " + " | ".join(l) + " |")
    else:
        w = [max(len(head[i]), *(len(l[i]) for l in lines)) for i in range(len(head))]
        print("  ".join(h.ljust(w[i]) for i, h in enumerate(head)))
        for l in lines:
            print("  ".join(c.ljust(w[i]) if i < 2 else c.rjust(w[i]) for i, c in enumerate(l)))


def show(a) -> None:
    rows = list(csv.DictReader(open(RESULTS, encoding="utf-8")))
    if a.time:
        rows = [r for r in rows if float(r["time"]) == a.time]
    runs = defaultdict(list)
    for r in rows:
        runs[(r["branch"], r["sha"], r["config"], r["time"], r["note"])].append(r)
    for (branch, sha, config, t, note), rs in runs.items():
        print(f"\n## {branch} @ {sha}  config={config}  time={t}s  {note}")
        print_summary(summarize(rs), md=a.md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="default")
    ap.add_argument("--time", type=float, default=None, help="ALNS seconds per run (quick: 60, full: 300)")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--cores", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--scenarios", default=None, help="comma list of names (e.g. big,fake_comp_a); default all")
    ap.add_argument("--note", default="")
    ap.add_argument("--md", action="store_true", help="print the summary as a markdown table")
    ap.add_argument("--show", action="store_true", help="print summaries of all saved runs and exit")
    a = ap.parse_args()
    if a.show:
        return show(a)
    a.time = a.time or 60.0

    branch, sha = git("rev-parse", "--abbrev-ref", "HEAD"), git("rev-parse", "--short", "HEAD")
    dirty = "yes" if git("status", "--porcelain", "--untracked-files=no", "--", "solver") else "no"
    want = set(a.scenarios.split(",")) if a.scenarios else None
    insts = [s for s in scenarios() if want is None or s[1] in want]
    if want and want - {s[1] for s in insts}:
        sys.exit(f"unknown scenarios: {sorted(want - {s[1] for s in insts})}")
    seeds = [int(x) for x in a.seeds.split(",")]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    jobs = [dict(set=st, scenario=name, snapshot=snap, folder=folder, seed=seed, time=a.time, config=a.config,
                 out=ROOT / "out" / "bench" / f"{stamp}_{branch.replace('/', '-')}_{sha}_{a.config}"
                     / f"{name}{'_' + snap if snap else ''}" / f"seed{seed}")
            for st, name, snap, folder in insts for seed in seeds]
    eta = len(jobs) * (a.time + 15) / a.cores / 60
    print(f"{branch}@{sha} (solver dirty: {dirty})  config={a.config}  {len(jobs)} runs x {a.time:.0f}s "
          f"on {a.cores} processes, about {eta:.0f} min")

    rows = []
    t0 = time.time()
    with ThreadPoolExecutor(a.cores) as ex:
        for row in ex.map(run_job, jobs):
            rows.append(row)
            print(f"  {row['scenario']:12} seed {row['seed']}  {row['score']:8.2f}  "
                  f"{row['fulfilled']}/{row['orders']}  {row['iterations']} it  [{time.time() - t0:.0f}s]",
                  flush=True)

    RESULTS.parent.mkdir(exist_ok=True)
    new = not RESULTS.exists()
    when = time.strftime("%Y-%m-%d %H:%M")
    with open(RESULTS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(dict(r, when=when, branch=branch, sha=sha, dirty=dirty, note=a.note))
    print()
    print_summary(summarize(rows), md=a.md)
    print(f"\n{len(rows)} rows appended to {RESULTS.relative_to(ROOT)}; plans in {jobs[0]['out'].parent.parent}")


if __name__ == "__main__":
    main()
