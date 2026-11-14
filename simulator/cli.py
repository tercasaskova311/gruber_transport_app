"""Command line entry point.

  python -m gruber.cli validate <scenario> <plan.json>   # free API Validate + local check
  python -m gruber.cli local <scenario> <plan.json>      # local simulate + score only
"""
from __future__ import annotations

import argparse
import json

from . import loader, simulator
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
    a = ap.parse_args()
    {"local": cmd_local, "validate": cmd_validate}[a.cmd](a)


if __name__ == "__main__":
    main()
