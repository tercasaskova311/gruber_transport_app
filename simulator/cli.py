"""Command line entry point.

  python -m gruber.cli validate <scenario> <plan.json>   # free API Validate + local check
  python -m gruber.cli local <scenario> <plan.json>      # local simulate + score only
  python -m gruber.cli submit <scenario> <plan.json> [--snapshot <dir>] [--dry-run] [--i-am-sure]
                                                # all free checks, then ONE Score call after y/N
"""
from __future__ import annotations

import argparse
import json
import sys

from . import loader, simulator, submit
from .api import Client


def _load_plan(path):
    with open(path) as f:
        return json.load(f)


def cmd_local(a):
    sc = loader.load(a.scenario, a.snapshot)
    r = simulator.api_round(simulator.score(sc, _load_plan(a.plan)))
    m = r["metrics"]
    print(f"score {r['score']}  breakdown {r['breakdown']}")
    print(f"fulfilled {m['orders_fulfilled']}/{m['orders_total']}  km {m['total_km']} "
          f"(loaded {m['loaded_km']})  late {m['orders_late']} too_late {m['orders_too_late']}")
    print(f"violations: {len(r['validation']['violations'])}")


def cmd_validate(a):
    sc = loader.load(a.scenario, a.snapshot)
    plan = _load_plan(a.plan)
    api = Client().validate(a.scenario, plan)
    loc = simulator.simulate(sc, plan)["validation"]
    print("API  :", api["is_valid"], api["violations"][:10])
    print("local:", loc["is_valid"], loc["violations"][:10])


def main():
    ap = argparse.ArgumentParser(prog="gruber")
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("local", "validate"):
        p = sp.add_parser(name); p.add_argument("scenario"); p.add_argument("plan")
        p.add_argument("--snapshot")
    p = sp.add_parser("submit", help="checked submission: fresh data, local score, Validate, y/N, Score")
    p.add_argument("scenario"); p.add_argument("plan")
    p.add_argument("--snapshot", help="snapshot the plan was built on (folder or name; default: latest)")
    p.add_argument("--dry-run", action="store_true", help="run every check, send nothing to Score")
    p.add_argument("--i-am-sure", action="store_true", help="required for scenario_competitive")
    a = ap.parse_args()
    if a.cmd == "submit":
        sys.exit(submit.run(a.scenario, a.plan, snapshot=a.snapshot, dry_run=a.dry_run, i_am_sure=a.i_am_sure))
    {"local": cmd_local, "validate": cmd_validate}[a.cmd](a)


if __name__ == "__main__":
    main()
