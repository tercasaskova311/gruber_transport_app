"""prepare.py : rebuild solver tables (prepare.sql) from cur_* and run checks.

    python prepare.py          # exits non-zero if a check fails
"""
import sys

import duckdb

import checks
import config as C
from fetch import init_schema, log


def run(con):
    init_schema(con)
    con.execute((C.HERE / "prepare.sql").read_text())
    log("prepare.sql done")
    checks.run(con)


if __name__ == "__main__":
    with duckdb.connect(str(C.DB_PATH)) as con:
        try:
            run(con)
        except checks.CheckFailed as e:
            print(e, file=sys.stderr)
            sys.exit(1)
        print(con.sql("SELECT * FROM scenario_stats ORDER BY scenario_id"))
