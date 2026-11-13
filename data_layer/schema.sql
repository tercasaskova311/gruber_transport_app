-- schema.sql : raw, append-only storage + "current" views + solver output tables.
-- Safe to run many times (fetch.py runs it on every start).
--
-- Rule of thumb: rows are NEVER updated or deleted. Every fetch that sees a
-- change writes a new snapshot_id. Everything downstream reads cur_* only.
-- All ids are VARCHAR so "C001", "17" and "T-3" all work.

-- One row per (snapshot, scenario). Written LAST in the fetch transaction,
-- so a half-written snapshot is never visible through the cur_* views.
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id   VARCHAR   NOT NULL,   -- e.g. 20261113T175000Z (sortable)
    scenario_id   VARCHAR   NOT NULL,
    fetched_at    TIMESTAMP NOT NULL,
    fingerprint   VARCHAR   NOT NULL,   -- sha256 of /Scenarios + each /Cities
    name          VARCHAR,
    cities_count  INTEGER,              -- as announced by /Scenarios (used by checks)
    trucks_count  INTEGER,
    orders_count  INTEGER,
    PRIMARY KEY (snapshot_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS cities (
    snapshot_id VARCHAR NOT NULL,
    scenario_id VARCHAR NOT NULL,
    id          VARCHAR NOT NULL,
    name        VARCHAR,
    country     VARCHAR,
    latitude    DOUBLE,
    longitude   DOUBLE,
    raw_json    JSON,
    PRIMARY KEY (snapshot_id, scenario_id, id)
);

CREATE TABLE IF NOT EXISTS trucks (
    snapshot_id VARCHAR NOT NULL,
    scenario_id VARCHAR NOT NULL,
    id          VARCHAR NOT NULL,
    start_city  VARCHAR,
    capacity_kg DOUBLE,
    type        VARCHAR,                -- standard | refrigerated | hazmat
    cost_per_km DOUBLE,
    co2_per_km  DOUBLE,
    raw_json    JSON,
    PRIMARY KEY (snapshot_id, scenario_id, id)
);

-- Time windows are stored in MINUTES since Day 1 06:00 (NULL = no limit).
-- How they are extracted from the API JSON lives in fetch.py:parse_time_windows.
CREATE TABLE IF NOT EXISTS orders (
    snapshot_id         VARCHAR NOT NULL,
    scenario_id         VARCHAR NOT NULL,
    id                  VARCHAR NOT NULL,
    pickup_city         VARCHAR,
    delivery_city       VARCHAR,
    weight_kg           DOUBLE,
    required_truck_type VARCHAR,        -- NULL = any truck
    value               DOUBLE,
    pickup_tw_from      INTEGER,
    pickup_tw_to        INTEGER,
    delivery_tw_from    INTEGER,
    delivery_tw_to      INTEGER,
    raw_json            JSON,           -- keep everything, in case we mapped a field wrong
    PRIMARY KEY (snapshot_id, scenario_id, id)
);

-- Distance matrix in long format: one row per (from, to), km.
CREATE TABLE IF NOT EXISTS distances (
    snapshot_id VARCHAR NOT NULL,
    scenario_id VARCHAR NOT NULL,
    from_city   VARCHAR NOT NULL,
    to_city     VARCHAR NOT NULL,
    km          DOUBLE,
    PRIMARY KEY (snapshot_id, scenario_id, from_city, to_city)
);

-- ---------------------------------------------------------------------------
-- Current views: the latest snapshot per scenario. Downstream reads ONLY these.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cur_snapshots AS
SELECT s.*
FROM snapshots s
JOIN (SELECT scenario_id, max(snapshot_id) AS snapshot_id
      FROM snapshots GROUP BY scenario_id) l
  USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW cur_cities AS
SELECT t.* FROM cities t JOIN cur_snapshots s USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW cur_trucks AS
SELECT t.* FROM trucks t JOIN cur_snapshots s USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW cur_orders AS
SELECT t.* FROM orders t JOIN cur_snapshots s USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW cur_distances AS
SELECT t.* FROM distances t JOIN cur_snapshots s USING (scenario_id, snapshot_id);

-- ---------------------------------------------------------------------------
-- Solver output. One row per solver run, plus its stop-by-stop plan.
-- load.py:save_run() writes these.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id          VARCHAR   NOT NULL PRIMARY KEY,
    scenario_id     VARCHAR   NOT NULL,
    snapshot_id     VARCHAR   NOT NULL,  -- which data the plan was built on
    created_at      TIMESTAMP NOT NULL,
    algo            VARCHAR,
    params_json     JSON,
    local_score     DOUBLE,              -- our own evaluator
    api_score       DOUBLE,              -- what the official API said (NULL if not submitted)
    score_value     DOUBLE,              -- score parts (adapt names to the official formula)
    score_cost      DOUBLE,
    score_co2       DOUBLE,
    score_km        DOUBLE,
    n_orders_served INTEGER,
    violations      INTEGER,
    plan_json       JSON                 -- exactly what we submitted / would submit
);

CREATE TABLE IF NOT EXISTS run_stops (
    run_id        VARCHAR NOT NULL,
    truck_id      VARCHAR NOT NULL,
    seq           INTEGER NOT NULL,      -- 0, 1, 2 ... per truck
    action        VARCHAR NOT NULL,      -- start | pickup | delivery | end
    order_id      VARCHAR,
    city_id       VARCHAR,
    arrival_min   INTEGER,
    departure_min INTEGER,
    load_kg       DOUBLE,                -- load after this stop
    late_min      INTEGER,               -- 0 if on time
    PRIMARY KEY (run_id, truck_id, seq)
);
