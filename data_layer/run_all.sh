#!/usr/bin/env bash
# fetch (only writes if the API changed) -> prepare.sql -> checks.  Extra args go to fetch.py.
#   ./run_all.sh               ./run_all.sh --force           ./run_all.sh --scenario 2
set -euo pipefail
cd "$(dirname "$0")"
python fetch.py --no-prepare "$@"
python prepare.py
