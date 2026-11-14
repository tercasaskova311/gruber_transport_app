"""simulator/submit.py with the API client replaced by a fake: no real Score or Simulate call is made."""
import copy
import csv
import json
import shutil

import pytest

from simulator import loader, simulator, submit
from simulator.api import COMPETITIVE

PARTS = ("cities", "trucks", "orders", "distance_matrix")


class FakeClient:
    """Serves one snapshot's data; Validate and Score answer like the exact simulator."""

    def __init__(self, data, validate_violations=None, score_shift=0.0):
        self.data = data
        self.validate_violations = validate_violations
        self.score_shift = score_shift
        self.score_calls = []
        self.validate_calls = 0

    def cities(self, sid): return self.data["cities"]
    def trucks(self, sid): return self.data["trucks"]
    def orders(self, sid): return self.data["orders"]
    def distance_matrix(self, sid): return self.data["distance_matrix"]

    def team(self):
        raise RuntimeError("404 Not Found")

    def _sc(self, sid):
        return loader.from_raw(sid, *(self.data[n] for n in PARTS))

    def validate(self, sid, plan):
        self.validate_calls += 1
        if self.validate_violations is not None:
            return {"is_valid": False, "violations": self.validate_violations}
        return simulator.simulate(self._sc(sid), plan)["validation"]

    def simulate(self, *a, **k):
        raise AssertionError("submit must never call Simulate")

    def score(self, sid, plan, approval=None, i_am_sure=False):
        assert approval is not None, "submit must pass its own approval (no second prompt)"
        approval.consume(sid, "Score")
        self.score_calls.append((sid, plan))
        r = simulator.api_round(simulator.score(self._sc(sid), plan))
        r["score"] = round(r["score"] + self.score_shift, 2)
        return r


class Answers:
    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else ""


@pytest.fixture
def env(tmp_path):
    """A private data/ and out/ folder holding one snapshot, plus a valid one-order plan."""
    snaps = loader.list_snapshots("scenario_small")
    if not snaps:
        pytest.skip("no snapshot")
    data = {n: json.loads((snaps[-1] / f"{n}.json").read_text()) for n in PARTS}
    sc = loader.from_raw("x", *(data[n] for n in PARTS))
    plan = None
    for t in sc.trucks:
        for o in sc.orders:
            cand = {t.id: [{"action": "pickup", "order": o.id}, {"action": "delivery", "order": o.id}]}
            r = simulator.score(sc, cand)
            if not r["validation"]["violations"] and not r["_unverified"] and r["metrics"]["orders_fulfilled"]:
                plan = cand
                break
        if plan:
            break
    assert plan

    class Env:
        pass
    e = Env()
    e.data, e.plan, e.tmp = data, plan, tmp_path
    e.data_dir, e.out_dir = tmp_path / "data", tmp_path / "out" / "submissions"

    def setup(scenario):
        shutil.copytree(snaps[-1], e.data_dir / scenario / "20000101_000000")
        return e.write_plan(plan)

    def write_plan(p, name="plan.json"):
        f = tmp_path / name
        f.write_text(json.dumps(p))
        return f

    e.db_rows = []          # what would have been written to the team database

    def fake_save(scenario, snapshot_id, plan, result, algo, source, params=None):
        e.db_rows.append(dict(scenario=scenario, snapshot_id=snapshot_id, plan=plan, result=result,
                              algo=algo, source=source, params=params))
        return "fake-run-id", "saved to the database: fake"

    def run(scenario, plan_file, client, ask=None, **kw):
        ask = ask or Answers()
        kw.setdefault("save_result", fake_save)     # tests never touch the real database
        code = submit.run(scenario, plan_file, client=client, ask=ask, data_dir=e.data_dir,
                          out_dir=e.out_dir, **kw)
        return code, ask
    e.setup, e.write_plan, e.run = setup, write_plan, run
    return e


def log_rows(e):
    f = e.out_dir / "log.csv"
    return list(csv.DictReader(open(f, encoding="utf-8"))) if f.exists() else []


def test_changed_data_stops_at_step_1_and_saves_new_snapshot(env, capsys):
    pf = env.setup("scenario_small")
    data = copy.deepcopy(env.data)
    data["orders"][0]["weight_kg"] += 1
    c = FakeClient(data)
    code, ask = env.run("scenario_small", pf, c, Answers("y"))
    out = capsys.readouterr().out
    assert code != 0 and "orders changed: 1 modified" in out
    assert c.validate_calls == 0 and not c.score_calls and not ask.prompts
    snaps = sorted(p.name for p in (env.data_dir / "scenario_small").iterdir())
    assert len(snaps) == 2      # the fresh data was saved next to the old snapshot
    new = env.data_dir / "scenario_small" / snaps[-1]
    assert json.loads((new / "orders.json").read_text()) == data["orders"]


def test_plan_with_violation_stops_at_step_2(env, capsys):
    env.setup("scenario_small")
    bad = {t: stops[:1] for t, stops in env.plan.items()}        # pickup without delivery
    c = FakeClient(env.data)
    code, ask = env.run("scenario_small", env.write_plan(bad, "bad.json"), c, Answers("y"))
    assert code != 0 and "STOPPED at step 2" in capsys.readouterr().out
    assert c.validate_calls == 0 and not c.score_calls and not ask.prompts


def test_validate_violation_stops_at_step_3(env, capsys):
    pf = env.setup("scenario_small")
    c = FakeClient(env.data, validate_violations=[{"rule": "x", "truck": "T01", "order": "O001", "message": "m"}])
    code, ask = env.run("scenario_small", pf, c, Answers("y"))
    assert code != 0 and "STOPPED at step 3" in capsys.readouterr().out
    assert c.validate_calls == 1 and not c.score_calls and not ask.prompts


@pytest.mark.parametrize("answer", ["n", "", "maybe"])
def test_answering_no_sends_nothing(env, answer):
    pf = env.setup("scenario_small")
    c = FakeClient(env.data)
    code, ask = env.run("scenario_small", pf, c, Answers(answer))
    assert code != 0 and len(ask.prompts) == 1 and not c.score_calls and not log_rows(env)
    assert not env.db_rows


def test_dry_run_asks_and_sends_nothing(env, capsys):
    pf = env.setup("scenario_small")
    c = FakeClient(env.data)
    code, ask = env.run("scenario_small", pf, c, Answers("y"), dry_run=True)
    assert code == 0 and "DRY RUN" in capsys.readouterr().out
    assert c.validate_calls == 1 and not ask.prompts and not c.score_calls and not log_rows(env)


def test_competitive_without_i_am_sure_sends_nothing(env, capsys):
    pf = env.setup(COMPETITIVE)
    c = FakeClient(env.data)
    code, ask = env.run(COMPETITIVE, pf, c, Answers("y", COMPETITIVE))
    assert code != 0 and "--i-am-sure" in capsys.readouterr().out
    assert not ask.prompts and not c.score_calls and not log_rows(env)


def test_competitive_needs_the_typed_scenario_name(env):
    pf = env.setup(COMPETITIVE)
    c = FakeClient(env.data)
    code, ask = env.run(COMPETITIVE, pf, c, Answers("y", "yes"), i_am_sure=True)
    assert code != 0 and len(ask.prompts) == 2 and not c.score_calls
    code, ask = env.run(COMPETITIVE, pf, c, Answers("y", COMPETITIVE), i_am_sure=True)
    assert code == 0 and len(c.score_calls) == 1 and len(log_rows(env)) == 1


def test_competitive_stops_when_log_shows_limit_reached(env, capsys):
    pf = env.setup(COMPETITIVE)
    c = FakeClient(env.data)
    for i in range(3):
        assert env.run(COMPETITIVE, pf, c, Answers("y", COMPETITIVE), i_am_sure=True)[0] == 0
    code, ask = env.run(COMPETITIVE, pf, c, Answers("y", COMPETITIVE), i_am_sure=True)
    assert code != 0 and len(c.score_calls) == 3 and not ask.prompts


def test_successful_run_writes_response_plan_copy_and_log(env, capsys):
    pf = env.setup("scenario_small")
    c = FakeClient(env.data)
    code, ask = env.run("scenario_small", pf, c, Answers("y"))
    out = capsys.readouterr().out
    assert code == 0 and c.score_calls == [("scenario_small", env.plan)]
    assert "in sync" in out and "DIFFER" not in out
    sub = env.out_dir / "scenario_small"
    resp = [f for f in sub.iterdir() if f.name.endswith("_score.json")]
    plans = [f for f in sub.iterdir() if f.name.endswith("_plan.json")]
    assert len(resp) == 1 and len(plans) == 1
    assert json.loads(plans[0].read_text()) == env.plan
    saved = json.loads(resp[0].read_text())
    rows = log_rows(env)
    assert len(rows) == 1 and rows[0]["scenario"] == "scenario_small"
    assert float(rows[0]["api_score"]) == saved["score"] == float(rows[0]["local_score"])
    assert len(rows[0]["plan_sha256"]) == 64
    # the API response is handed to the team database as an API Score row
    assert len(env.db_rows) == 1
    db = env.db_rows[0]
    assert (db["scenario"], db["snapshot_id"], db["source"], db["algo"]) ==            ("scenario_small", "20000101_000000", "score", "submit")
    assert db["result"] == saved and db["plan"] == env.plan
    assert db["params"]["plan_sha256"] == rows[0]["plan_sha256"]
    # a second run shows the recorded call and warns that this plan was already sent
    env.run("scenario_small", pf, c, Answers("n"))
    out = capsys.readouterr().out
    assert "scenario_small: 1" in out and "already sent" in out and len(c.score_calls) == 1


def test_score_mismatch_is_shown_prominently(env, capsys):
    pf = env.setup("scenario_small")
    c = FakeClient(env.data, score_shift=-1.5)
    code, _ = env.run("scenario_small", pf, c, Answers("y"))
    assert code == 0 and "API SCORE AND LOCAL SCORE DIFFER" in capsys.readouterr().out


def test_failed_score_request_is_logged_as_used(env, capsys):
    pf = env.setup("scenario_small")
    c = FakeClient(env.data)

    def boom(*a, **k):
        raise TimeoutError("timed out")
    c.score = boom
    code, _ = env.run("scenario_small", pf, c, Answers("y"))
    rows = log_rows(env)
    assert code != 0 and len(rows) == 1 and rows[0]["api_score"].startswith("ERROR")


def test_database_failure_does_not_fail_the_submission(env, capsys):
    pf = env.setup("scenario_small")
    c = FakeClient(env.data)

    def broken(*a, **k):
        raise RuntimeError("database is locked")
    code, _ = env.run("scenario_small", pf, c, Answers("y"), save_result=broken)
    out = capsys.readouterr().out
    assert code == 0 and "not saved to the database" in out
    assert len(c.score_calls) == 1 and len(log_rows(env)) == 1


def test_dry_run_and_failed_checks_write_nothing_to_the_database(env):
    pf = env.setup("scenario_small")
    env.run("scenario_small", pf, FakeClient(env.data), Answers("y"), dry_run=True)
    env.run("scenario_small", pf, FakeClient(env.data, validate_violations=[{"rule": "x"}]), Answers("y"))
    assert not env.db_rows


def test_results_db_roundtrip_with_a_real_duckdb(env, monkeypatch):
    """End to end into a temporary DuckDB file built from ingestion/schema.sql."""
    duckdb = pytest.importorskip("duckdb")
    from ingestion import config as C
    from simulator import results_db
    db = env.tmp / "test.duckdb"
    con = duckdb.connect(str(db))
    con.execute((C.HERE / "schema.sql").read_text(encoding="utf-8"))
    con.close()
    monkeypatch.setattr(C, "DB_PATH", db)
    sc = loader.from_raw("scenario_small", *(env.data[n] for n in PARTS))
    resp = simulator.api_round(simulator.score(sc, env.plan))
    run_id, msg = results_db.save("scenario_small", "snapX", env.plan, resp, algo="submit", source="score")
    assert run_id, msg
    con = duckdb.connect(str(db), read_only=True)
    row = con.execute("SELECT scenario_id, snapshot_id, source, algo, score, n_violations, plan_json "
                      "FROM results.runs WHERE run_id = ?", [run_id]).fetchone()
    con.close()
    assert row[:4] == ("scenario_small", "snapX", "score", "submit")
    assert row[4] == resp["score"] and row[5] == 0 and json.loads(row[6]) == env.plan


def test_results_db_without_database_only_reports(env, monkeypatch):
    from simulator import results_db
    try:
        from ingestion import config as C
        monkeypatch.setattr(C, "DB_PATH", env.tmp / "missing.duckdb")
    except Exception:
        pass                                    # duckdb not installed: save() must still not raise
    run_id, msg = results_db.save("scenario_small", "s", env.plan, {}, algo="submit", source="score")
    assert run_id is None and "not saved to the database" in msg

