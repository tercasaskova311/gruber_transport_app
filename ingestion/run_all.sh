#!/usr/bin/env bash
# fetch (only writes if the API changed) -> prepare.sql -> checks.  Extra args go to fetch.py.
#   ./run_all.sh               ./run_all.sh --force           ./run_all.sh --scenario 2
# Override the interpreter with PYTHON=..., e.g. PYTHON=.venv/bin/python ./run_all.sh
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"   # Windows consoles: tables print box characters
"$PY" fetch.py --no-prepare "$@"
"$PY" prepare.py
