"""Named solver configurations: keyword arguments passed to solver.alns().

    python run.py <scenario_dir> --config default

Experiments add entries here so the benchmark (tools/bench.py) can compare them by name.
"""
CONFIGS: dict[str, dict] = {
    # ejection-chain local search (ejection.py) is on by default since algo/ejection was accepted
    "default": {"eject": True},
    "no-eject": {},
    # algo/tw-first (twfirst.py): tw_first = share of the time spent on the time-window skeleton;
    # protect_release = chance that a destroy step may still remove a skeleton order (0 = never)
    "tw-first": {"eject": True, "tw_first": 0.2, "protect_release": 0.0},
    "tw-first-soft": {"eject": True, "tw_first": 0.2, "protect_release": 0.25},
    "tw-first-free": {"eject": True, "tw_first": 0.2, "protect_release": 1.0},
    "block": {"block": True},                       # "blocking removal" destroy operator: no benefit measured
    "eject+block": {"eject": True, "block": True},
}
