-- schema.sql : raw, append-only storage + "current" views + solver output tables.
-- Safe to run many times (fetch.py runs it on every start).
--
-- Three schemas, one writer each:
--   raw.*      API data, append-only          <- fetch.py      (this file)
--   prep.*     solver-ready tables, rebuilt   <- prepare.sql
--   results.*  solver runs                    <- load.save_run (this file)
--
-- Rule of thumb: raw rows are NEVER updated or deleted. Every fetch that sees a
-- change writes a new snapshot_id. Everything downstream reads raw.cur_* only.
-- All ids are VARCHAR so "C001", "17" and "T-3" all work.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS results;

-- One row per (snapshot, scenario). Written LAST in the fetch transaction,
-- so a half-written snapshot is never visible through the cur_* views.
CREATE TABLE IF NOT EXISTS raw.snapshots (
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

CREATE TABLE IF NOT EXISTS raw.cities (
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

CREATE TABLE IF NOT EXISTS raw.trucks (
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
CREATE TABLE IF NOT EXISTS raw.orders (
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
CREATE TABLE IF NOT EXISTS raw.distances (
    snapshot_id VARCHAR NOT NULL,
    scenario_id VARCHAR NOT NULL,
    from_city   VARCHAR NOT NULL,
    to_city     VARCHAR NOT NULL,
    km          DOUBLE,
    PRIMARY KEY (snapshot_id, scenario_id, from_city, to_city)
);

-- ---------------------------------------------------------------------------
-- Current views (raw.cur_*): the latest snapshot per scenario. Downstream reads ONLY these.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW raw.cur_snapshots AS
SELECT s.*
FROM raw.snapshots s
JOIN (SELECT scenario_id, max(snapshot_id) AS snapshot_id
      FROM raw.snapshots GROUP BY scenario_id) l
  USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW raw.cur_cities AS
SELECT t.* FROM raw.cities t JOIN raw.cur_snapshots s USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW raw.cur_trucks AS
SELECT t.* FROM raw.trucks t JOIN raw.cur_snapshots s USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW raw.cur_orders AS
SELECT t.* FROM raw.orders t JOIN raw.cur_snapshots s USING (scenario_id, snapshot_id);

CREATE OR REPLACE VIEW raw.cur_distances AS
SELECT t.* FROM raw.distances t JOIN raw.cur_snapshots s USING (scenario_id, snapshot_id);

-- ---------------------------------------------------------------------------
-- results.* : every plan we evaluated, via the API or a local evaluator.
-- Column names follow the API's response (Swagger: ScoreResult / SimulationMetrics /
-- ValidationResult / TruckMetrics / ScheduleEntry), so load.save_run() fills them straight
-- from the API's JSON. Columns a response doesn't contain stay NULL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS results.runs (
    run_id                 VARCHAR   NOT NULL PRIMARY KEY,
    scenario_id            VARCHAR   NOT NULL,
    snapshot_id            VARCHAR   NOT NULL,  -- which data the plan was built on
    created_at             TIMESTAMP NOT NULL,
    algo                   VARCHAR,
    params_json            JSON,
    source                 VARCHAR   NOT NULL,  -- local | validate | simulate | score
    plan_hash              VARCHAR   NOT NULL,  -- same plan => same hash (compare local vs API)
    score                  DOUBLE,              -- 0..1000 (local or API Score)
    is_valid               BOOLEAN,
    n_violations           INTEGER,
    -- breakdown (0..100 each; penalty / late_penalty in points)
    fulfillment            DOUBLE,
    cost_efficiency        DOUBLE,
    loaded_ratio           DOUBLE,
    co2_efficiency         DOUBLE,
    penalty                DOUBLE,
    late_penalty           DOUBLE,
    -- metrics
    total_km               DOUBLE,
    loaded_km              DOUBLE,
    empty_km               DOUBLE,
    total_cost             DOUBLE,
    total_co2              DOUBLE,
    orders_fulfilled       INTEGER,
    orders_total           INTEGER,
    value_fulfilled        DOUBLE,
    value_lost_to_lateness DOUBLE,
    value_total            DOUBLE,
    truck_utilization      DOUBLE,
    orders_late            INTEGER,
    orders_too_late        INTEGER,
    total_late_min         INTEGER,
    penalized_late_min     INTEGER,
    plan_json              JSON,                -- exactly what was submitted
    response_json          JSON                 -- the full answer (minus per-truck detail, see below)
);

CREATE TABLE IF NOT EXISTS results.run_violations (
    run_id   VARCHAR NOT NULL,
    rule     VARCHAR NOT NULL,                  -- unknown_truck, capacity_exceeded, ...
    truck_id VARCHAR,
    order_id VARCHAR,
    message  VARCHAR
);

CREATE TABLE IF NOT EXISTS results.run_trucks (
    run_id             VARCHAR NOT NULL,
    truck_id           VARCHAR NOT NULL,
    total_km           DOUBLE,
    loaded_km          DOUBLE,
    empty_km           DOUBLE,
    cost               DOUBLE,
    co2                DOUBLE,
    max_load_kg        DOUBLE,
    utilization        DOUBLE,
    finish_min         INTEGER,
    driving_min        INTEGER,
    break_and_rest_min INTEGER,
    route              VARCHAR[],               -- city ids in visiting order
    PRIMARY KEY (run_id, truck_id)
);

CREATE TABLE IF NOT EXISTS results.run_stops (
    run_id        VARCHAR NOT NULL,
    truck_id      VARCHAR NOT NULL,
    seq           INTEGER NOT NULL,             -- 0, 1, 2 ... per truck
    action        VARCHAR,                      -- pickup | delivery
    order_id      VARCHAR,
    city_id       VARCHAR,
    arrival_min   INTEGER,
    wait_min      INTEGER,
    late_min      INTEGER,                      -- 0 = on time
    departure_min INTEGER,
    PRIMARY KEY (run_id, truck_id, seq)
);
