"""Build the generalization set: fake scenarios the solver is never tuned on.

  python -m tools.make_fakes

Runs solver/make_fake_scenario.py (fixed seeds) and rewrites orders.json into the real API
format (pickup_window / delivery_window / value) so simulator.loader and the exact simulator read
them like a real snapshot. Result: data/fake/<name>/. The folders are committed, so every
branch is measured on exactly the same data; re-run only to add new ones.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKES = {            # name: (preset, seed)
    "fake_big_a": ("big", 101),
    "fake_comp_a": ("competitive", 102),
    "fake_comp_b": ("competitive", 103),
}


def main():
    for name, (preset, seed) in FAKES.items():
        out = ROOT / "data" / "fake" / name
        if (out / "orders.json").exists():
            print(f"{name}: exists, kept")
            continue
        subprocess.run([sys.executable, str(ROOT / "solver" / "make_fake_scenario.py"), "--preset", preset,
                        "--seed", str(seed), "--out", str(out)], check=True)
        p = out / "orders.json"
        orders = json.loads(p.read_text(encoding="utf-8"))
        for o in orders:
            w = o.pop("time_window", None)
            o["pickup_window"] = o["delivery_window"] = None
            if w:
                key = "pickup_window" if w.get("applies_to") == "pickup" else "delivery_window"
                o[key] = {"from": int(w["from"]), "to": int(w["to"])}
        p.write_text(json.dumps(orders, indent=1), encoding="utf-8")
        n_tw = sum(1 for o in orders if o["pickup_window"] or o["delivery_window"])
        print(f"{name}: {len(orders)} orders, {n_tw} with a time window")


if __name__ == "__main__":
    main()
