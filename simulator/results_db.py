"""Optional: store an evaluated plan in the team database (results.*, read by the dashboard).

Thin wrapper around ingestion.load.save_run that never raises: saving to the database is a
convenience, so a missing duckdb package, a missing database file or a locked database only
produces a message. The plan and response files written by the caller are the real record.
"""
from __future__ import annotations

from types import SimpleNamespace


def save(scenario: str, snapshot_id: str, plan: dict, result: dict, algo: str, source: str,
         params: dict | None = None) -> tuple[str | None, str]:
    """Insert one row into results.runs (+ per-truck / per-stop detail if the result has it).

    source: "score" = `result` is the API's Score response; "local" = our simulator's result.
    Returns (run_id or None, message for the user).
    """
    try:
        from ingestion import config as C
        from ingestion import load as dl
    except Exception as e:                      # duckdb not installed, ...
        return None, f"not saved to the database ({type(e).__name__}: {e})"
    if not C.DB_PATH.exists():
        return None, f"not saved to the database (no database file at {C.DB_PATH})"
    con = None
    try:
        con = dl.connect(read_only=False, tries=5)
        ref = SimpleNamespace(scenario_id=scenario, snapshot_id=snapshot_id)
        run_id = dl.save_run(con, ref, plan, result, algo=algo, source=source, params=params)
        return run_id, f"saved to the database: results.runs run_id {run_id} (source={source}, algo={algo})"
    except Exception as e:                      # locked by another process, schema missing, ...
        return None, f"not saved to the database ({type(e).__name__}: {str(e)[:200]})"
    finally:
        if con is not None:
            con.close()
