"""Parity test between the local simulator and the API's Simulate / Score.

  python -m tools.parity build  [--n 20] [--seed 1]       # create plan sets (no API calls)
  python -m tools.parity send   <scenario> [--kinds Simulate,Score]   # ASKS y/n, then sends
  python -m tools.parity compare [<scenario>]              # offline: saved API responses vs local

Sending refuses scenario_competitive unless --i-am-sure is given.
"""
from __future__ import annotations

import argparse
import json
import random
import sys

from simulator import api, config, loader, simulator
from tools import plangen

PARITY_DIR = config.DATA_DIR / "parity"
SCEN = ["scenario_small", "scenario_middle", "scenario_big"]


def build_set(sc, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    tw = [o.id for o in sc.orders if o.pw or o.dw]
    out = [{"name": "sample", "plan": sc.sample_plan}]
    specs = []
    for i in range(n):
        k = i % 5
        if k == 0:     # all orders, sequential P->D, all trucks
            specs.append(("full_seq", dict(frac=1.0, consolidate=False)))
        elif k == 1:   # all orders, consolidated
            specs.append(("full_consol", dict(frac=1.0, consolidate=True)))
        elif k == 2:   # long routes: few trucks carry everything -> breaks & rests
            specs.append(("long_routes", dict(frac=1.0, consolidate=True, n_trucks=2)))
        elif k == 3:   # time-window heavy: all TW orders + some others, few trucks -> lateness
            specs.append(("tw_heavy", dict(frac=0.3, consolidate=True, n_trucks=3, must_include=tw)))
        else:          # partial
            specs.append(("partial", dict(frac=rng.choice([0.2, 0.5, 0.8]), consolidate=rng.random() < .5)))
    for i, (name, kw) in enumerate(specs):
        p = plangen.random_valid_plan(sc, rng, **kw)
        # n_trucks may exclude trucks that are the only compatible ones -> fine (orders dropped)
        assert simulator.simulate(sc, p)["validation"]["is_valid"], name
        out.append({"name": f"{name}_{i}", "plan": p})
    out += late_band_plans(sc, rng, k=4)
    # two invalid plans: how skipped / rejected / mismatched stops are simulated
    for j in range(2):
        base = plangen.random_valid_plan(sc, rng, frac=0.4, consolidate=True, n_trucks=3)
        out.append({"name": f"invalid_{j}", "plan": plangen.mutate_invalid(sc, base, rng, n=6)})
    return out


def late_band_plans(sc, rng, k=4, tries=4000):
    """Plans where some time-window order is 1..60 min late (value decay band),
    plus waiting before windows. Found by random search on short single-truck routes."""
    tw = [o for o in sc.orders if o.pw or o.dw]
    found = []
    seen = set()
    if not tw:
        return found
    for _ in range(tries):
        if len(found) >= k:
            break
        o = rng.choice(tw)
        trucks = [t for t in sc.trucks if plangen.compatible(sc, o, t)]
        if not trucks:
            continue
        t = rng.choice(trucks)
        others = [x for x in sc.orders if x.id != o.id and plangen.compatible(sc, x, t)]
        pre = rng.sample(others, min(len(others), rng.randint(0, 3)))
        stops = []
        for x in pre:
            stops += [{"action": "pickup", "order": x.id}, {"action": "delivery", "order": x.id}]
        stops += [{"action": "pickup", "order": o.id}, {"action": "delivery", "order": o.id}]
        p = {t.id: stops}
        m = simulator.simulate(sc, p)["metrics"]
        sig = (o.id, m["penalized_late_min"])
        if m["orders_late"] >= 1 and m["orders_too_late"] == 0 and sig not in seen:
            seen.add(sig)
            found.append({"name": f"late_band_{len(found)}", "plan": p})
    return found


def cmd_build(a):
    PARITY_DIR.mkdir(parents=True, exist_ok=True)
    for sid in SCEN:
        sc = loader.load(sid)
        s = build_set(sc, a.n, a.seed)
        fn = PARITY_DIR / f"{sid}.json"
        fn.write_text(json.dumps({"scenario": sid, "snapshot": sc.snapshot, "plans": s}, indent=1))
        print(f"{fn}: {len(s)} plans (snapshot {sc.snapshot})")


def _fresh_matches_snapshot(c: api.Client, sc) -> bool:
    fresh = loader.from_raw(sc.id, c.cities(sc.id), c.trucks(sc.id), c.orders(sc.id),
                            c.distance_matrix(sc.id))
    return ([vars(o) for o in fresh.orders] == [vars(o) for o in sc.orders]
            and [vars(t) for t in fresh.trucks] == [vars(t) for t in sc.trucks]
            and (fresh.dist == sc.dist).all())


def cmd_send(a):
    sid = a.scenario
    sset = json.loads((PARITY_DIR / (a.set or f"{sid}.json")).read_text())
    assert sset["scenario"] == sid, "plan set is for another scenario"
    sc = loader.load(sid, sset["snapshot"])
    c = api.Client()
    if not _fresh_matches_snapshot(c, sc):
        sys.exit("Server data differs from the snapshot the plans were built on (restart?). "
                 "Fetch a new snapshot and rebuild.")
    plans = sset["plans"]
    if a.only:
        plans = [p for p in plans if p["name"] in a.only.split(",")]
    kinds = a.kinds.split(",")
    approval = api.confirm_batch(sid, set(kinds), len(plans) * len(kinds),
                                 f"parity test: {len(plans)} plans x {kinds}",
                                 plans=[p["plan"] for p in plans], i_am_sure=a.i_am_sure)
    out = PARITY_DIR / "responses" / sid
    out.mkdir(parents=True, exist_ok=True)
    for p in plans:
        for k in kinds:
            fn = c.simulate if k == "Simulate" else c.score
            r = fn(sid, p["plan"], approval=approval)
            (out / f"{p['name']}.{k}.json").write_text(json.dumps(
                {"snapshot": sc.snapshot, "plan": p["plan"], "response": r}, indent=1))
            print(f"  {p['name']} {k}: ok")


# ---------------------------------------------------------------- comparison
def _diff(path, a, b, out, tol):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append(f"{path}.{k}: missing locally (api={str(a[k])[:60]})")
            else:
                _diff(f"{path}.{k}", a[k], b[k], out, tol)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: len api={len(a)} local={len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(f"{path}[{i}]", x, y, out, tol)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > tol:
            out.append(f"{path}: api={a} local={b}")
    elif a != b:
        out.append(f"{path}: api={a!r} local={b!r}")


def compare_one(sc, plan, kind, resp, tol=1e-9):
    local = simulator.api_round(simulator.score(sc, plan))
    if kind == "Simulate":
        local_view = local["metrics"] if "trucks" in resp else local
    else:
        local_view = local
    diffs: list[str] = []
    _diff("", resp, local_view, diffs, tol)
    return diffs


def cmd_compare(a):
    root = PARITY_DIR / "responses"
    sids = [a.scenario] if a.scenario else sorted(p.name for p in root.iterdir())
    n = ok = 0
    for sid in sids:
        for f in sorted((root / sid).glob("*.json")):
            rec = json.loads(f.read_text())
            sc = loader.load(sid, rec["snapshot"])
            kind = f.stem.split(".")[-1]
            diffs = compare_one(sc, rec["plan"], kind, rec["response"], a.tol)
            n += 1
            if diffs:
                print(f"DIFF {sid}/{f.stem}: {len(diffs)} field(s)")
                for d in diffs[: a.show]:
                    print("    ", d)
            else:
                ok += 1
    print(f"\n{ok}/{n} responses match exactly (numeric tol {a.tol})")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build"); b.add_argument("--n", type=int, default=20); b.add_argument("--seed", type=int, default=1)
    s = sp.add_parser("send"); s.add_argument("scenario"); s.add_argument("--kinds", default="Simulate,Score")
    s.add_argument("--only"); s.add_argument("--set", help="plan set file in data/parity/"); s.add_argument("--i-am-sure", action="store_true")
    c = sp.add_parser("compare"); c.add_argument("scenario", nargs="?"); c.add_argument("--tol", type=float, default=1e-9)
    c.add_argument("--show", type=int, default=12)
    a = ap.parse_args()
    {"build": cmd_build, "send": cmd_send, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
