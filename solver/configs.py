"""Named solver configurations: keyword arguments passed to solver.alns().

    python run.py <scenario_dir> --config default

Experiments add entries here so the benchmark (tools/bench.py) can compare them by name.
"""
CONFIGS: dict[str, dict] = {
    # ejection-chain local search (ejection.py) is on by default since algo/ejection was accepted
    "default": {"eject": True},
    "no-eject": {},
    "block": {"block": True},                       # "blocking removal" destroy operator: no benefit measured
    "eject+block": {"eject": True, "block": True},
}
