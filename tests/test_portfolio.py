"""tools/portfolio.py: runs several solver runs and keeps the plan with the best exact score."""
import json

import pytest

from simulator import loader, simulator
from tools import portfolio


def test_parse_runs():
    assert portfolio.parse_runs("default:1,tw-first:2") == [("default", 1), ("tw-first", 2)]
    assert portfolio.parse_runs("default") == [("default", 1)]
    with pytest.raises(ValueError):
        portfolio.parse_runs("default:1,default:1")


def test_best_plan_is_the_highest_exact_score(tmp_path):
    snaps = loader.list_snapshots("scenario_small")
    if not snaps:
        pytest.skip("no snapshot")
    best, rows = portfolio.run_portfolio(snaps[-1], [("default", 1), ("tw-first", 1)], 1.0, 2, tmp_path)
    assert len(rows) == 2 and best["score"] == max(r["score"] for r in rows)
    assert all(r["violations"] == 0 for r in rows)
    plan = json.loads((tmp_path / "best_plan.json").read_text(encoding="utf-8"))
    r = simulator.score(loader.load("scenario_small"), plan)
    assert not r["validation"]["violations"]
    assert r["score"] == pytest.approx(best["score"], abs=1e-3)
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["best"]["config"] == best["config"]


def test_save_best_to_db_passes_the_exact_local_result(tmp_path):
    snaps = loader.list_snapshots("scenario_small")
    if not snaps:
        pytest.skip("no snapshot")
    runs = [("default", 1)]
    best, _ = portfolio.run_portfolio(snaps[-1], runs, 1.0, 1, tmp_path)
    got = []

    def fake_save(sid, snapshot_id, plan, result, algo, source, params=None):
        got.append((sid, snapshot_id, plan, result, algo, source, params))
        return "id", "saved"
    assert portfolio.save_best_to_db(snaps[-1], tmp_path, best, 1.0, runs, save=fake_save) == ("id", "saved")
    sid, snapshot_id, plan, result, algo, source, params = got[0]
    assert (sid, snapshot_id, algo, source) == ("scenario_small", snaps[-1].name, "portfolio", "local")
    assert result["score"] == pytest.approx(best["score"], abs=1e-3)
    assert not result["validation"]["violations"] and not any(k.startswith("_") for k in result)
    assert params["config"] == "default" and params["seed"] == 1
    json.dumps(result)          # must be storable as JSON

