"""tools/portfolio.py: runs several solver runs and keeps the plan with the best exact score."""
import json

import pytest

from gruber import loader, simulator
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
