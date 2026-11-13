-- prepare.sql : solver-ready tables built from cur_* only.
-- Rebuilt from scratch every time (CREATE OR REPLACE). Every join carries scenario_id.
--
-- Time model (minutes since Day 1 06:00):
--   drive_minutes = ceil(km * 60 / 70), 30 min service at every stop,
--   arriving early = wait, a window bound "to" is the latest SERVICE START.
-- Breaks / driving-hour limits are NOT modelled here (alone_* are optimistic).

CREATE OR REPLACE MACRO drive_minutes(km) AS CAST(ceil(km * 60.0 / 70.0 - 1e-9) AS INTEGER);
CREATE OR REPLACE MACRO service_min() AS 30;

-- ---------------------------------------------------------------------------
-- city_index : dense 0..N-1 per scenario (row/col of the distance matrices)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE city_index AS
SELECT scenario_id, snapshot_id, id AS city_id, name, country, latitude, longitude,
       CAST(row_number() OVER (PARTITION BY scenario_id ORDER BY id) - 1 AS INTEGER) AS city_pos
FROM cur_cities;

-- ---------------------------------------------------------------------------
-- city_distances : full N x N matrix in long form
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE city_distances AS
SELECT d.scenario_id,
       a.city_pos AS from_pos, b.city_pos AS to_pos,
       d.from_city, d.to_city,
       d.km, drive_minutes(d.km) AS drive_minutes
FROM cur_distances d
JOIN city_index a ON a.scenario_id = d.scenario_id AND a.city_id = d.from_city
JOIN city_index b ON b.scenario_id = d.scenario_id AND b.city_id = d.to_city;

-- ---------------------------------------------------------------------------
-- truck_features
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE truck_features AS
SELECT t.scenario_id,
       CAST(row_number() OVER (PARTITION BY t.scenario_id ORDER BY t.id) - 1 AS INTEGER) AS truck_pos,
       t.id AS truck_id,
       t.start_city, c.city_pos AS start_pos,
       t.capacity_kg, t.type, t.cost_per_km, t.co2_per_km,
       CAST(dense_rank() OVER (PARTITION BY t.scenario_id ORDER BY t.cost_per_km) AS INTEGER) AS cost_rank,  -- 1 = cheapest
       CAST(dense_rank() OVER (PARTITION BY t.scenario_id ORDER BY t.co2_per_km)  AS INTEGER) AS co2_rank     -- 1 = cleanest
FROM cur_trucks t
LEFT JOIN city_index c ON c.scenario_id = t.scenario_id AND c.city_id = t.start_city;

-- ---------------------------------------------------------------------------
-- order_base : order + indices + direct leg + window maths (helper for the rest)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE order_base AS
WITH o AS (
    SELECT o.*,
           CAST(row_number() OVER (PARTITION BY o.scenario_id ORDER BY o.id) - 1 AS INTEGER) AS order_pos,
           p.city_pos AS pickup_pos, d.city_pos AS delivery_pos
    FROM cur_orders o
    LEFT JOIN city_index p ON p.scenario_id = o.scenario_id AND p.city_id = o.pickup_city
    LEFT JOIN city_index d ON d.scenario_id = o.scenario_id AND d.city_id = o.delivery_city
)
SELECT o.scenario_id, o.order_pos, o.id AS order_id,
       o.pickup_city, o.delivery_city, o.pickup_pos, o.delivery_pos,
       o.weight_kg, o.required_truck_type, o.value,
       o.pickup_tw_from, o.pickup_tw_to, o.delivery_tw_from, o.delivery_tw_to,
       l.km AS direct_km, l.drive_minutes AS direct_drive_min,
       CASE WHEN (o.pickup_tw_from IS NOT NULL OR o.pickup_tw_to IS NOT NULL)
             AND (o.delivery_tw_from IS NOT NULL OR o.delivery_tw_to IS NOT NULL) THEN 'both'
            WHEN o.pickup_tw_from IS NOT NULL OR o.pickup_tw_to IS NOT NULL THEN 'pickup'
            WHEN o.delivery_tw_from IS NOT NULL OR o.delivery_tw_to IS NOT NULL THEN 'delivery'
            ELSE 'none' END AS time_window_type,
       -- earliest / latest moment the pickup service can START and still meet both windows
       -- (arriving early at delivery is fine: the truck waits)
       coalesce(o.pickup_tw_from, 0) AS earliest_pickup_minute,
       CASE WHEN o.pickup_tw_to IS NULL AND o.delivery_tw_to IS NULL THEN NULL
            ELSE least(coalesce(o.pickup_tw_to, 2147483647),
                       coalesce(o.delivery_tw_to - service_min() - l.drive_minutes, 2147483647)) END AS latest_pickup_minute
FROM o
LEFT JOIN city_distances l ON l.scenario_id = o.scenario_id AND l.from_pos = o.pickup_pos AND l.to_pos = o.delivery_pos;

-- ---------------------------------------------------------------------------
-- order_truck_options : one row per (order, truck) that CAN carry it
--   type rule: order with no required type fits any truck; otherwise types must match
--   alone_*: truck drives start -> pickup -> delivery with only this order
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE order_truck_options AS
WITH x AS (
    SELECT o.scenario_id, o.order_pos, o.order_id, t.truck_pos AS truck_pos, t.truck_id,
           s.km AS empty_km_to_pickup, s.drive_minutes AS start_to_pickup_min,
           o.direct_km, o.direct_drive_min, t.cost_per_km, t.co2_per_km,
           o.pickup_tw_to, o.delivery_tw_from, o.delivery_tw_to,
           greatest(s.drive_minutes, coalesce(o.pickup_tw_from, 0)) AS pickup_start_min
    FROM order_base o
    JOIN truck_features t
      ON t.scenario_id = o.scenario_id
     AND (o.required_truck_type IS NULL OR lower(t.type) = lower(o.required_truck_type))
     AND o.weight_kg <= t.capacity_kg
    LEFT JOIN city_distances s ON s.scenario_id = o.scenario_id AND s.from_pos = t.start_pos AND s.to_pos = o.pickup_pos
)
SELECT scenario_id, order_pos, order_id, truck_pos, truck_id,
       empty_km_to_pickup,
       empty_km_to_pickup + direct_km                  AS alone_km,
       (empty_km_to_pickup + direct_km) * cost_per_km  AS alone_cost_eur,
       (empty_km_to_pickup + direct_km) * co2_per_km   AS alone_co2_kg,
       pickup_start_min,
       pickup_start_min + service_min() + direct_drive_min AS delivery_arrival_min,
       (pickup_tw_to IS NULL OR pickup_start_min <= pickup_tw_to)
       AND (delivery_tw_to IS NULL
            OR greatest(pickup_start_min + service_min() + direct_drive_min, coalesce(delivery_tw_from, 0))
               <= delivery_tw_to) AS alone_on_time
FROM x;

-- ---------------------------------------------------------------------------
-- order_features : order_base + truck availability + priority (1 = plan first)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE order_features AS
WITH n AS (
    SELECT scenario_id, order_pos,
           count(*) AS trucks_that_fit,
           count(*) FILTER (WHERE alone_on_time) AS trucks_on_time,
           min(alone_cost_eur) AS min_solo_cost
    FROM order_truck_options GROUP BY ALL
)
SELECT o.*,
       latest_pickup_minute - earliest_pickup_minute AS time_window_slack_minutes,   -- NULL = no deadline; < 0 = impossible even driving direct
       coalesce(n.trucks_that_fit, 0) AS trucks_that_fit,
       coalesce(n.trucks_on_time, 0)   AS trucks_on_time,
       n.min_solo_cost,
       CAST(row_number() OVER (
           PARTITION BY o.scenario_id
           ORDER BY coalesce(latest_pickup_minute - earliest_pickup_minute, 1e9),  -- tight windows first
                    coalesce(n.trucks_that_fit, 0),                      -- few trucks first
                    o.value DESC, o.weight_kg DESC, o.order_pos) AS INTEGER) AS planning_order
FROM order_base o
LEFT JOIN n ON n.scenario_id = o.scenario_id AND n.order_pos = o.order_pos;

-- ---------------------------------------------------------------------------
-- order_similarity : a < b, how "close" two orders are (for clustering / LNS removal)
--   similarity_distance: lower = more related. km part normalised by the scenario's
--   longest leg, time part by one day, +1 if they need different truck types.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE order_similarity AS
WITH mx AS (SELECT scenario_id, nullif(max(km), 0) AS max_km FROM city_distances GROUP BY ALL)
SELECT a.scenario_id, a.order_pos AS a_pos, b.order_pos AS b_pos,
       lp.km AS pickup_km, ld.km AS delivery_km,
       (lp.km + ld.km) / (2 * mx.max_km)
       + abs(a.earliest_pickup_minute - b.earliest_pickup_minute) / 1440.0
       + CASE WHEN coalesce(a.required_truck_type, '') <> coalesce(b.required_truck_type, '') THEN 1 ELSE 0 END
         AS similarity_distance
FROM order_base a
JOIN order_base b ON b.scenario_id = a.scenario_id AND a.order_pos < b.order_pos
JOIN mx ON mx.scenario_id = a.scenario_id
JOIN city_distances lp ON lp.scenario_id = a.scenario_id AND lp.from_pos = a.pickup_pos   AND lp.to_pos = b.pickup_pos
JOIN city_distances ld ON ld.scenario_id = a.scenario_id AND ld.from_pos = a.delivery_pos AND ld.to_pos = b.delivery_pos;

-- ---------------------------------------------------------------------------
-- scenario_summary : one row per scenario, to eyeball difficulty
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE scenario_summary AS
WITH o AS (
    SELECT scenario_id,
           count(*) AS n_orders,
           sum(weight_kg) AS total_weight_kg,
           max(weight_kg) AS max_order_kg,
           sum(value) AS total_value,
           avg(CASE WHEN time_window_type <> 'none' THEN 1.0 ELSE 0.0 END) AS pct_with_tw,
           sum(direct_km) AS ideal_km,   -- sum of pickup->delivery km: lower bound on loaded km
           count(*) FILTER (WHERE trucks_that_fit = 0) AS orders_no_truck_fits,
           count(*) FILTER (WHERE time_window_slack_minutes < 0)        AS n_orders_tw_impossible,
           count(*) FILTER (WHERE trucks_on_time = 0)   AS n_orders_no_solo_feasible
    FROM order_features GROUP BY ALL
), t AS (
    SELECT scenario_id, count(*) AS n_trucks, sum(capacity_kg) AS total_capacity_kg,
           max(capacity_kg) AS max_truck_kg,
           min(cost_per_km) AS min_cost_per_km, min(co2_per_km) AS min_co2_per_km
    FROM truck_features GROUP BY ALL
), c AS (
    SELECT scenario_id, count(*) AS n_cities FROM city_index GROUP BY ALL
)
SELECT s.scenario_id, s.snapshot_id, s.name, c.n_cities, t.n_trucks, o.n_orders,
       o.total_weight_kg, t.total_capacity_kg,
       o.total_weight_kg / nullif(t.total_capacity_kg, 0) AS weight_capacity_ratio,
       o.max_order_kg, t.max_truck_kg,
       o.total_value, o.pct_with_tw, o.ideal_km,
       t.min_cost_per_km, t.min_co2_per_km,
       o.orders_no_truck_fits, o.n_orders_tw_impossible, o.n_orders_no_solo_feasible
FROM cur_snapshots s
LEFT JOIN c USING (scenario_id)
LEFT JOIN t USING (scenario_id)
LEFT JOIN o USING (scenario_id);
