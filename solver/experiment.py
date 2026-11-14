"""
experiment.py — A/B test solver variants: same scenarios, same seeds, same time budget,
one change per variant. Every run is scored by the verified simulator and saved in
results.runs with params_json = {experiment, variant, seed, time_limit_s, iterations, git}.

    python experiment.py --experiment ab1 --variants baseline route7d prune \
                         --scenarios scenario_big scenario_competitive --seeds 0-4 --time 20
    python experiment.py --experiment ab1 --report        # comparison table only

Rules: variants run one after another (never in parallel, so each gets the same CPU), and
interleaved per seed (baseline, B, C, baseline, B, C, ...) so slow-downs hit all equally.
"""
from __future__ import annotations

import argparse
import statistics as st
import subprocess
import time

import evaluator as ev
import settings
from instance import Instance, load_from_db
from run import save_to_results
from solver import alns, check_plan, construct


# ---------------------------------------------------------------- variants (one change each)
def v_baseline(inst: Instance) -> None:
    """A: the solver as it is."""


def v_route7d(inst: Instance) -> None:
    """No truck route may end later than 7 days after the start (dispatcher realism)."""
    ev.MAX_FINISH_MIN = 7 * 24 * 60


def v_prune(inst: Instance) -> None:
    """Drop order-truck pairs that can't be on time (<= 60 min late) even carrying nothing else.
    Exact: prep's alone_* times are lower bounds (start at minute 0, drive straight, no breaks)."""
    from ingestion import load as dl
    con = dl.connect()
    try:
        ok = con.execute("""SELECT order_pos, truck_pos FROM prep.order_truck_options
                            WHERE scenario_id = ? AND alone_fulfillable""", [inst.scenario_id]).fetchall()
    finally:
        con.close()
    keep = {(o, k) for o, k in ok}
    inst.compatible = [[k for k in ks if (o, k) in keep] for o, ks in enumerate(inst.compatible)]


VARIANTS = {"baseline": v_baseline, "route7d": v_route7d, "prune": v_prune}


# ---------------------------------------------------------------- running
def git_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             cwd=settings.ROOT).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "solver", "database"],
                               capture_output=True, text=True, cwd=settings.ROOT).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def run_one(scenario: str, variant: str, seed: int, time_limit: float, experiment: str, git: str) -> None:
    ev.MAX_FINISH_MIN = None                       # reset global switches before every run
    inst = load_from_db(scenario)
    VARIANTS[variant](inst)
    t0 = time.time()
    start = max((construct(inst, seed=seed, regret=r) for r in (1, 2, 3)), key=lambda s: s.S)
    best, log = alns(inst, start, time_limit=time_limit, seed=seed, verbose=False)
    assert not check_plan(inst, best), check_plan(inst, best)
    print(f"{scenario:<22} {variant:<9} seed {seed}: {best.S:8.2f}  "
          f"({log.iterations} it, {time.time() - t0:.0f}s)", flush=True)
    save_to_results(inst, {"alns": best.to_plan(inst)},
                    {"experiment": experiment, "variant": variant, "seed": seed,
                     "time_limit_s": time_limit, "iterations": log.iterations, "git": git})
    ev.MAX_FINISH_MIN = None


# ---------------------------------------------------------------- report
def report(experiment: str, baseline: str = "baseline") -> None:
    from ingestion import load as dl
    con = dl.connect()
    try:
        rows = con.execute("""
            SELECT r.scenario_id, r.params_json->>'variant' AS variant,
                   CAST(r.params_json->>'seed' AS INT) AS seed, r.score, r.orders_fulfilled, r.orders_total,
                   r.n_violations, CAST(r.params_json->>'iterations' AS INT) AS it,
                   max(t.finish_min) / 1440.0 AS longest_days, r.empty_km / nullif(r.total_km, 0) * 100 AS empty_pct
            FROM results.runs r JOIN results.run_trucks t USING (run_id)
            WHERE r.params_json->>'experiment' = ? AND r.algo = 'alns'
            GROUP BY ALL ORDER BY 1, 2, 3""", [experiment]).fetchall()
    finally:
        con.close()
    if not rows:
        print(f"no runs for experiment {experiment!r}")
        return
    by = {}
    for sid, var, seed, s, of, ot, nv, it, ld, ep in rows:
        by.setdefault(sid, {}).setdefault(var, {})[seed] = (s, of, ot, nv, it, ld, ep)

    for sid, variants in by.items():
        print(f"\n{sid}")
        print(f"  {'variant':<9} {'n':>2} {'mean':>8} {'sd':>5} {'min':>8} {'max':>8} {'Δ vs A':>7} {'wins':>5}"
              f" {'orders':>7} {'viol':>4} {'longest':>8} {'empty%':>6} {'iters':>6}")
        base = variants.get(baseline, {})
        for var, seeds in variants.items():
            sc = [v[0] for v in seeds.values()]
            paired = [seeds[k][0] - base[k][0] for k in seeds if k in base]
            delta = st.mean(paired) if paired and var != baseline else None
            wins = f"{sum(d > 0 for d in paired)}/{len(paired)}" if var != baseline and paired else ""
            print(f"  {var:<9} {len(sc):>2} {st.mean(sc):8.2f} {(st.stdev(sc) if len(sc) > 1 else 0):5.2f}"
                  f" {min(sc):8.2f} {max(sc):8.2f} {(f'{delta:+.2f}' if delta is not None else ''):>7} {wins:>5}"
                  f" {st.mean(v[1] for v in seeds.values()):7.1f} {max(v[3] for v in seeds.values()):>4}"
                  f" {max(v[5] for v in seeds.values()):6.1f} d {st.mean(v[6] for v in seeds.values()):6.2f}"
                  f" {st.mean(v[4] for v in seeds.values()):6.0f}")


def parse_seeds(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--variants", nargs="+", default=["baseline"], choices=list(VARIANTS))
    ap.add_argument("--scenarios", nargs="+", default=["scenario_big", "scenario_competitive"])
    ap.add_argument("--seeds", default="0-4")
    ap.add_argument("--time", type=float, default=20)
    ap.add_argument("--report", action="store_true", help="only print the comparison table")
    args = ap.parse_args()
    if not args.report:
        git = git_version()
        for sid in args.scenarios:
            for seed in parse_seeds(args.seeds):
                for var in args.variants:
                    run_one(sid, var, seed, args.time, args.experiment, git)
    report(args.experiment)


if __name__ == "__main__":
    main()
