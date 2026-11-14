#!/usr/bin/env bash
# The whole pipeline, one command:
#   1. data layer: fetch API -> raw.* -> prep.* -> checks   (ingestion/run_all.sh)
#   2. tests: solver loader + evaluator still match           (pytest)
#   3. solver: every scenario in solver/settings.py -> solver/out/<scenario>/ + results.*
#
#   ./run_all.sh                     # defaults from solver/settings.py
#   ./run_all.sh --time 300          # extra args go to solver/run.py
#   SKIP_FETCH=1 ./run_all.sh        # reuse the current DB (no API calls at all)
#   PYTHON=.venv/bin/python ./run_all.sh
#
# No Simulate/Score API calls are made: scoring is local (simulator/simulator.py).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"   # Windows consoles: tables print box characters

if [ -z "${SKIP_FETCH:-}" ]; then
  echo "== 1/3 data layer"
  PYTHON="$PY" ./ingestion/run_all.sh
else
  echo "== 1/3 data layer: skipped (SKIP_FETCH)"
fi

echo "== 2/3 tests"
"$PY" -m pytest -q tests

echo "== 3/3 solver"
(cd solver && "$PY" run.py "$@")
