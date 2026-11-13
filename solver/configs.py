"""Named solver configurations: keyword arguments passed to solver.alns().

    python run.py <scenario_dir> --config default

Experiments add entries here so the benchmark (tools/bench.py) can compare them by name.
"""
CONFIGS: dict[str, dict] = {
    "default": {},
}
