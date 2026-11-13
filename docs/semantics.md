# API behaviour (verified)

Established from API responses, not from the PDF alone. Validation rules: 120 random
(mostly invalid) plans against the free Validate endpoint, identical violation lists.
Simulation/score: 154 Simulate + Score responses on small/middle/big (77 plans) match
the local simulator field by field, including every schedule entry, with zero tolerance
after API rounding.

## Data
- Orders: `pickup_window` / `delivery_window` = `{"from": int, "to": int}` (minutes from
  plan start) or `null`; `value` = 1 / 1.5 / 2.
- Distance matrix: integer km.

## Validation (`gruber/simulator.py`, first part of `simulate`)
- Trucks are processed in plan key order; stops in list order.
- Unknown truck: one `unknown_truck` violation, even for an empty list; stops not processed,
  do not claim orders.
- Per stop: unknown order -> `unknown_order` (order "" if missing). Then ownership: the first
  truck with *any* stop referencing a known order (even an invalid one) owns it; every stop
  on other trucks -> `order_assigned_multiple_times`, skipped.
- `truck_type_mismatch` is reported at every stop of the order (any action) until it has
  been successfully loaded on that truck. A mismatched order is still loaded, counts for
  capacity, drives loaded, but is never fulfilled.
- Then action (case-insensitive): unknown -> `unknown_action`.
- Pickup: already picked (incl. rejected) -> `duplicate_pickup`. Capacity: load + w > cap ->
  `capacity_exceeded`, pickup rejected, the truck does *not* drive there.
- Delivery: already delivered -> `duplicate_delivery`; not picked -> `delivery_before_pickup`;
  delivery of a rejected order -> silently ignored (no driving, not marked delivered).
- End of truck: picked, not delivered, not rejected -> `pickup_without_delivery`.
- Skipped stops do not drive and do not appear in the schedule or route.

## Time model
- Leg driving minutes = ceil(km * 60 / 70) per leg; 0 km legs take no time.
- Every executed stop: arrival, wait until window `from` if early, 30 min service.
- Driver counters: driving since last break (limit 270) and since last rest (limit 540).
  A break/rest is inserted when the truck needs to drive further and a limit is reached,
  including in the middle of a leg.
- **Stationary time counts toward the pause**: the inserted break is 45 min minus the
  minutes the truck has been standing still since it last drove (service + waiting, across
  consecutive same-city stops); same for the 11 h rest. Standing >= 45 min before driving
  resets the break counter.
- `break_and_rest_min` counts only the inserted minutes.
- Lateness = max(0, arrival - to). Value factor 1 - 0.5 * late/60; > 60 min -> not fulfilled.
- `orders_late` counts all late orders including the too-late ones; `penalized_late_min`
  sums lateness of fulfilled late orders; `total_late_min` sums `late_min` over all stops.

## Rounding
Score and breakdown, costs and CO2: 2 decimals. Utilization and order values: 4 decimals.
The score is computed from unrounded components and then rounded.

## Not observed (unverified)
- Standing still >= 11 h before driving: assumed to count as a daily rest.
- An order late at both pickup and delivery: lateness assumed = max of the two.
Window generation makes both practically unreachable (windows are set close to the earliest
arrival of the nearest truck); `simulate()` returns `_unverified` notes if a plan hits them.
