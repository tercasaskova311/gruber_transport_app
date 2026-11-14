"""
run.py — one command: build the initial plan, optimize it, compare, save everything.

    python run.py                                   # every scenario in settings.SCENARIOS, from the DB
    python run.py scenario_big --time 300 --seed 1  # one scenario from the DB
    python run.py data/scenario_big/<ts>           # a JSON folder (detected automatically)
    python run.py data/fake/fake_comp_a --config tw-first --seed 2 --out /tmp/x   # tools/bench.py, tools/portfolio.py

Defaults come from settings.py; command-line flags override them.

Outputs in settings.OUT_DIR/<scenario_id>/ (DB) or <scenario_dir>/out/ (JSON), or --out:
    plan_initial.json   plan_optimized.json   (official submission format)
    compare.md          compare.json          (initial vs optimized)
    history.csv         operators.json        (convergence + ALNS operator stats, for the app)
    result.json                               (score, config, timings: read by tools/bench.py)
With the DB source, both plans are also scored by the verified simulator (simulator/simulator.py) and
stored in results.* (turn off with --no-save).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import settings
from compare import compare
from configs import CONFIGS
from instance import Instance, list_db_scenarios, load_from_db, load_instance
from solver import Solution, alns, check_plan, construct


def solve(inst: Instance, out: Path, time_limit: float, seed: int, quiet: bool,
          config: str = "default") -> tuple[Solution, Solution]:
    out.mkdir(parents=True, exist_ok=True)
    print(f"Loaded {len(inst.trucks)} trucks, {inst.n_orders} orders, {len(inst.city_ids)} cities")

    cfg = dict(CONFIGS[config])
    tw_share = cfg.pop("tw_first", 0.0)
    protect_release = cfg.pop("protect_release", 0.0)
    alns_time = time_limit * (1.0 - tw_share)
    t0 = time.time()
    # greedy (regret=1) and regret-2/3 variants are cheap: build all, keep the best as the start
    variants = {rg: construct(inst, seed=seed, regret=rg) for rg in (1, 2, 3)}
    for rg, v in variants.items():
        print(f"      regret-{rg}: score {v.S:.2f}, {inst.n_orders - len(v.unassigned)}/{inst.n_orders} orders")
    initial = max(variants.values(), key=lambda v: v.S)
    print(f"[3+4] Initial plan (best ΔS insertion): score {initial.S:.2f}, "
          f"{inst.n_orders - len(initial.unassigned)}/{inst.n_orders} orders, {time.time() - t0:.1f}s")
    if tw_share:
        import twfirst
        initial, protect = twfirst.build(inst, time_limit=time_limit * tw_share, seed=seed)
        cfg.update(protect=protect, protect_release=protect_release)
        print(f"      tw-first: skeleton serves {len(protect)} time-window orders; "
              f"after fill-in score {initial.S:.2f}, {inst.n_orders - len(initial.unassigned)}/{inst.n_orders} orders")
    assert not check_plan(inst, initial), check_plan(inst, initial)

    print(f"[5] ALNS for {alns_time:.0f}s …")
    t_construct = time.time() - t0
    best, log = alns(inst, initial, time_limit=alns_time, seed=seed, verbose=not quiet, **cfg)
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
    (out / "result.json").write_text(json.dumps({
        "config": config, "seed": seed, "time": time_limit, "score": best.S,
        "initial_score": initial.S, "iterations": log.iterations,
        "eject_moves": log.eject_moves, "eject_seconds": round(log.eject_seconds, 2),
        "construct_s": round(t_construct, 2), "total_s": round(time.time() - t0, 2)}, indent=1), encoding="utf-8")
    with open(out / "history.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["iteration", "seconds", "best_score"])
        w.writerows(log.history)
    print("[6]", data["headline"].replace("**", ""))
    print(f"Saved to {out}/")
    return initial, best


def save_to_results(inst: Instance, plans: dict[str, dict], params: dict) -> None:
    """Score each plan with the verified simulator and store it in results.* (database)."""
    from types import SimpleNamespace

    from ingestion import load as dl                          # noqa: PLC0415
    from simulator import loader, simulator                       # noqa: PLC0415

    con = dl.connect(read_only=False)
    try:
        def raw(table):
            return [json.loads(r[0]) for r in con.execute(
                f"SELECT raw_json FROM raw.cur_{table} WHERE scenario_id = ? ORDER BY id",
                [inst.scenario_id]).fetchall()]

        dm: dict = {}
        for a, b, km in con.execute("SELECT from_city, to_city, km FROM raw.cur_distances WHERE scenario_id = ?",
                                    [inst.scenario_id]).fetchall():
            dm.setdefault(a, {})[b] = km
        sc = loader.from_raw(inst.scenario_id, raw("cities"), raw("trucks"), raw("orders"), dm,
                             snapshot=inst.snapshot_id)
        ref = SimpleNamespace(scenario_id=inst.scenario_id, snapshot_id=inst.snapshot_id)
        for algo, plan in plans.items():
            result = simulator.score(sc, plan)
            n_viol = len(result["validation"]["violations"])
            run_id = dl.save_run(con, ref, plan, result, algo=algo, source="local", params=params)
            print(f"    results.runs <- {algo}: score {result['score']:.2f}, {n_viol} violations ({run_id})")
    finally:
        con.close()


def main():
    try:
        sys.stdout.reconfigure(errors="replace")   # never crash on a console that lacks a symbol
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*",
                    help="scenario ids (DB) or folders (JSON); default: settings.SCENARIOS, "
                         "or every scenario in the DB")
    ap.add_argument("--source", choices=["db", "json"], default=settings.SOURCE,
                    help="an existing folder is always read as JSON")
    ap.add_argument("--time", type=float, default=settings.TIME_LIMIT_S, help="ALNS time limit in seconds")
    ap.add_argument("--seed", type=int, default=settings.SEED)
    ap.add_argument("--config", default="default", choices=sorted(CONFIGS), help="see configs.py")
    ap.add_argument("--out", default=None, help="output folder (one scenario only)")
    ap.add_argument("--no-save", action="store_true", help="don't write runs into results.*")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.source == "json" and not args.scenarios:
        ap.error("--source json needs a scenario folder")
    targets = args.scenarios or settings.SCENARIOS or list_db_scenarios()
    if args.out and len(targets) > 1:
        ap.error("--out needs exactly one scenario")
    summary = []
    for target in targets:
        print(f"\n===== {target} =====")
        from_db = args.source == "db" and not Path(target).is_dir()
        if from_db:
            inst = load_from_db(target)
            out = settings.OUT_DIR / target
        else:
            inst = load_instance(target)
            out = Path(target) / "out"
        if args.out:
            out = Path(args.out)
        initial, best = solve(inst, out, args.time, args.seed, args.quiet, args.config)
        summary.append((target, initial.S, best.S, inst.n_orders - len(best.unassigned), inst.n_orders))
        if from_db and settings.SAVE_TO_RESULTS and not args.no_save:
            save_to_results(inst, {"construct": initial.to_plan(inst), "alns": best.to_plan(inst)},
                            {"time_limit_s": args.time, "seed": args.seed, "config": args.config})

    if len(summary) > 1:
        print("\nscenario                 initial   optimized   orders")
        for name, s0, s1, n, N in summary:
            print(f"{Path(name).name:<22} {s0:9.2f} {s1:11.2f}   {n}/{N}")


if __name__ == "__main__":
    main()
