"""
run.py — one command: build the initial plan, optimize it, compare, save everything.

    python run.py data/scenario_competitive --time 300 --seed 1

Outputs in <scenario_dir>/out/:
    plan_initial.json   plan_optimized.json   (official submission format)
    compare.md          compare.json          (step 6: initial vs optimized)
    history.csv         operators.json        (convergence + ALNS operator stats, for the app)
"""
from __future__ import annotations

import argparse
import sys
import csv
import json
import time
from pathlib import Path

from compare import compare
from instance import load_instance
from solver import alns, check_plan, construct


def main():
    try:
        sys.stdout.reconfigure(errors="replace")   # never crash on a console that lacks a symbol
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario_dir")
    ap.add_argument("--time", type=float, default=60, help="ALNS time limit in seconds")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    inst = load_instance(args.scenario_dir)
    out = Path(args.scenario_dir) / "out"
    out.mkdir(exist_ok=True)
    print(f"Loaded {len(inst.trucks)} trucks, {inst.n_orders} orders, {len(inst.city_ids)} cities")

    t0 = time.time()
    # greedy (regret=1) and regret-2/3 variants are cheap: build all, keep the best as the start
    variants = {rg: construct(inst, seed=args.seed, regret=rg) for rg in (1, 2, 3)}
    for rg, v in variants.items():
        print(f"      regret-{rg}: score {v.S:.2f}, {inst.n_orders - len(v.unassigned)}/{inst.n_orders} orders")
    initial = max(variants.values(), key=lambda v: v.S)
    print(f"[3+4] Initial plan (best ΔS insertion): score {initial.S:.2f}, "
          f"{inst.n_orders - len(initial.unassigned)}/{inst.n_orders} orders, {time.time() - t0:.1f}s")
    assert not check_plan(inst, initial), check_plan(inst, initial)

    print(f"[5] ALNS for {args.time:.0f}s …")
    best, log = alns(inst, initial, time_limit=args.time, seed=args.seed, verbose=not args.quiet)
    issues = check_plan(inst, best)
    assert not issues, issues
    print(f"    {log.iterations} iterations, best score {best.S:.2f}")

    data, md = compare(inst, initial, best)
    (out / "plan_initial.json").write_text(json.dumps(initial.to_plan(inst), indent=1), encoding="utf-8")
    (out / "plan_optimized.json").write_text(json.dumps(best.to_plan(inst), indent=1), encoding="utf-8")
    (out / "compare.md").write_text(md, encoding="utf-8")
    (out / "compare.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (out / "operators.json").write_text(json.dumps({"destroy": log.destroy_stats, "repair": log.repair_stats,
                                                    "iterations": log.iterations}, indent=1), encoding="utf-8")
    with open(out / "history.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["iteration", "seconds", "best_score"])
        w.writerows(log.history)
    print("[6]", data["headline"].replace("**", ""))
    print(f"Saved to {out}/")


if __name__ == "__main__":
    main()
