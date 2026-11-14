"""Named solver configurations: keyword arguments passed to solver.alns().

    python run.py <scenario_dir> --config default

Experiments add entries here so the benchmark (tools/bench.py) can compare them by name.
"""
CONFIGS: dict[str, dict] = {
    "default": {},
    # algo/ejection: ejection-chain local search and/or the "blocking removal" destroy operator
    "eject": {"eject": True},
    "block": {"block": True},
    "eject+block": {"eject": True, "block": True},
}
