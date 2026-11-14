"""Fixed-work timing of the solver: same seed, fixed number of ALNS iterations.

  python -m tools.speedcheck [scenario_dir ...] [--iters 40]

Prints construction time, ALNS time, and the scores. With max_iters set, temperature depends
on elapsed time only through el/time_limit (time_limit is huge here), so the search path is
deterministic: a pure speed-up must print exactly the same scores as before.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "solver"))
from instance import load_instance  # noqa: E402
from solver import alns, construct  # noqa: E402

DEFAULT = ["data/scenario_competitive/20261113_192945", "data/scenario_big/20261113_192945",
           "data/fake/fake_comp_a"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*", default=DEFAULT)
    ap.add_argument("--iters", type=int, default=40)
    a = ap.parse_args()
    for d in a.dirs:
        inst = load_instance(ROOT / d)
        t0 = time.time()
        s = construct(inst, seed=1, regret=1)
        t1 = time.time()
        best, log = alns(inst, s, time_limit=1e9, seed=1, verbose=False, max_iters=a.iters)
        t2 = time.time()
        print(f"{Path(d).parent.name + '/' + Path(d).name:45} construct {t1 - t0:6.2f}s S={s.S:.6f} | "
              f"{log.iterations} it {t2 - t1:6.2f}s  best={best.S:.6f}", flush=True)


if __name__ == "__main__":
    main()
