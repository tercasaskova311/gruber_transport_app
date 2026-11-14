"""Portfolio run: several solver runs side by side on one snapshot, keep the best plan.

  python -m tools.portfolio <snapshot_dir> --time 300 [--runs default:1,tw-first:1,default:2,tw-first:2]
                            [--cores N] [--out DIR] [--log]

Each run is `solver/run.py <snapshot_dir> --config C --seed S --time T`. Every final plan is
scored with the exact simulator (gruber.simulator); a plan with a rule violation aborts. The
plan with the highest exact score is copied to <out>/best_plan.json, with a table of all runs
in <out>/summary.json. No API call is made here: Validate / Score are separate, manual steps.

--cores defaults to the number of runs, capped at the CPU count. More parallel runs than
physical cores makes every run slower (the solver is time-limited), so keep the machine idle.
--log appends the individual runs to experiments/results.csv (note "portfolio").
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools import bench

ROOT = bench.ROOT
DEFAULT_RUNS = "default:1,tw-first:1,default:2,tw-first:2"


def parse_runs(spec: str) -> list[tuple[str, int]]:
    runs = []
    for part in spec.split(","):
        config, _, seed = part.strip().partition(":")
        runs.append((config, int(seed or 1)))
    if len(set(runs)) != len(runs):
        raise ValueError(f"duplicate runs in {spec!r}")
    return runs


def run_portfolio(folder: Path, runs: list[tuple[str, int]], time_limit: float, cores: int,
                  out: Path, name: str | None = None) -> tuple[dict, list[dict]]:
    """Run all (config, seed) pairs, return (best row, all rows). Rows are bench.run_job rows."""
    folder = Path(folder).resolve()
    name = name or (folder.parent.name.replace("scenario_", "") if folder.parent.name.startswith("scenario_")
                    else folder.name)
    jobs = [dict(set="portfolio", scenario=name, snapshot=folder.name, folder=folder, seed=seed,
                 time=time_limit, config=config, out=out / f"{config}_seed{seed}")
            for config, seed in runs]
    with ThreadPoolExecutor(cores) as ex:
        rows = list(ex.map(bench.run_job, jobs))
    best = max(rows, key=lambda r: r["score"])
    src = out / f"{best['config']}_seed{best['seed']}" / "plan_optimized.json"
    shutil.copyfile(src, out / "best_plan.json")
    (out / "summary.json").write_text(json.dumps(
        {"snapshot_dir": str(folder), "time": time_limit, "cores": cores, "best": best, "runs": rows},
        indent=1), encoding="utf-8")
    return best, rows


def save_best_to_db(folder: Path, out: Path, best: dict, time_limit: float, runs, save=None):
    """Score best_plan.json with the exact simulator and store it in results.* (never raises)."""
    from simulator import results_db, simulator
    folder = Path(folder)
    sid = folder.parent.name if folder.parent.name.startswith("scenario_") else folder.name
    plan = json.loads((out / "best_plan.json").read_text(encoding="utf-8"))
    result = simulator.score(bench.load_dir(sid, folder), plan)
    result = {k: v for k, v in result.items() if not k.startswith("_")}
    return (save or results_db.save)(
        sid, folder.name, plan, result, algo="portfolio", source="local",
        params={"config": best["config"], "seed": best["seed"], "time_limit_s": time_limit,
                "runs": [f"{c}:{s}" for c, s in runs]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot_dir")
    ap.add_argument("--time", type=float, default=300.0, help="ALNS seconds per run")
    ap.add_argument("--runs", default=DEFAULT_RUNS, help="comma list of config:seed")
    ap.add_argument("--cores", type=int, default=None)
    ap.add_argument("--out", default=None, help="default: out/portfolio/<time stamp>_<scenario>")
    ap.add_argument("--log", action="store_true", help="append the runs to experiments/results.csv")
    ap.add_argument("--note", default="portfolio")
    ap.add_argument("--save-db", action="store_true",
                    help="also store the best plan in the team database (results.runs, source=local)")
    a = ap.parse_args()

    runs = parse_runs(a.runs)
    cores = a.cores or min(len(runs), os.cpu_count() or 1)
    folder = Path(a.snapshot_dir).resolve()
    label = folder.parent.name.replace("scenario_", "") if folder.parent.name.startswith("scenario_") else folder.name
    out = Path(a.out) if a.out else ROOT / "out" / "portfolio" / f"{time.strftime('%Y%m%d_%H%M%S')}_{label}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"{label}: {len(runs)} runs x {a.time:.0f}s on {cores} processes -> {out}")
    t0 = time.time()
    best, rows = run_portfolio(folder, runs, a.time, cores, out, name=label)
    for r in sorted(rows, key=lambda r: -r["score"]):
        mark = "*" if r is best else " "
        print(f" {mark} {r['config']:14} seed {r['seed']:<3} {r['score']:8.2f}  {r['fulfilled']}/{r['orders']}  "
              f"F {r['fulfillment']:.2f}  loaded {r['loaded_ratio']:.2f}  {r['iterations']} it  0 violations")
    print(f"best: {best['config']} seed {best['seed']}  exact score {best['score']:.2f}  "
          f"({time.time() - t0:.0f}s wall)\nplan: {out / 'best_plan.json'}")
    if a.save_db:
        print(save_best_to_db(folder, out, best, a.time, runs)[1])
    if a.log:
        branch, sha = bench.git("rev-parse", "--abbrev-ref", "HEAD"), bench.git("rev-parse", "--short", "HEAD")
        new = not bench.RESULTS.exists()
        with open(bench.RESULTS, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=bench.FIELDS)
            if new:
                w.writeheader()
            for r in rows:
                w.writerow(dict(r, when=time.strftime("%Y-%m-%d %H:%M"), branch=branch, sha=sha, dirty="",
                                note=f"{a.note} x{len(runs)} on {cores} cores"))


if __name__ == "__main__":
    main()
