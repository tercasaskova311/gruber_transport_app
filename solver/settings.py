"""
settings.py — solver run settings. Edit here, or override on the command line
(`python run.py --help`). Game rules (speed, breaks, lateness) are NOT settings: they live
in evaluator.py and must match the API.

The database location is NOT set here: it comes from data_layer/config.py (DB_PATH, which
also honours the DB_PATH / DATA_DIR environment variables), so the data layer and the
solver always use the same file.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))      # so `data_layer` and `gruber` import as packages

from data_layer.config import DB_PATH  # noqa: E402,F401

# Where the scenario data comes from:
#   "db"   -> data_layer's DuckDB (prep.* tables), built by data_layer/run_all.sh
#   "json" -> a folder with cities.json, trucks.json, orders.json, distance_matrix.json
SOURCE = "db"

# Scenarios solved by `python run.py` with no scenario given.
# None = every scenario in the DB (prep.scenario_summary); or a list, e.g. ["scenario_big"].
SCENARIOS = None

# ALNS
TIME_LIMIT_S = 60          # per scenario
SEED = 0

# Outputs
OUT_DIR = ROOT / "solver" / "out"      # out/<scenario_id>/plan_optimized.json, compare.md, ...
SAVE_TO_RESULTS = True                 # also store each run in results.* (DB source only)
