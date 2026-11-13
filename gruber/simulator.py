"""Exact local reproduction of the API's Validate / Simulate / Score.

Output dicts use the API's field names so they can be compared field by field.
Behaviour that the spec leaves open is collected in SEM and was fitted to API
responses (see tests/ and docs/semantics.md).
"""
from __future__ import annotations

import math

from .loader import Scenario

SPEED_KMH = 70
SERVICE_MIN = 30
BREAK_AFTER = 270      # 4.5 h driving
BREAK_MIN = 45
REST_AFTER = 540       # 9 h driving
REST_MIN = 660         # 11 h
LATE_MAX = 60
VIOLATION_PTS = 20

# Open questions about the time model; values are what the API does (fitted).
SEM = {
    # Stationary time (waiting + service, over consecutive stops) right before a
    # required break counts toward it: only the missing minutes are inserted.
    "break_topup": True,
    # Same for the 11 h daily rest.
    "rest_topup": True,
    # Stationary time >= REST_MIN before driving counts as a daily rest.
    "idle_counts_as_rest": True,
    # Do rejected pickups (capacity) still drive to the city?
    "rejected_pickup_drives": False,
    # Does an ignored delivery (of a rejected order) drive to the city?
    "ignored_delivery_drives": False,
    # Lateness reference: "arrival" (arrival - to) or "start" (service start - to).
    "late_ref": "arrival",
    # Order lateness for value decay and the 60 min cut-off = "max" over its stops
    # (verified: probes late 42+4 and 36+42 both kept 65 %).
    "order_late": "max",
    # orders_late counts every order with lateness > 0 (incl. > 60 min).
    "orders_late_incl_too_late": True,
}


def drive_minutes(km: float) -> int:
    return math.ceil(km * 60 / SPEED_KMH) if km > 0 else 0


class _Clock:
    """Driver clock: tracks driving since last break/rest and inserts them."""

    __slots__ = ("t", "since_break", "since_rest", "drive_total", "pause_total", "idle",
                 "n_unverified")

    def __init__(self):
        self.t = 0
        self.since_break = 0
        self.since_rest = 0
        self.drive_total = 0
        self.pause_total = 0
        self.idle = 0          # contiguous stationary minutes since last drive
        self.n_unverified = 0  # times an unverified rule (idle >= 11 h) mattered

    def stand(self, minutes: int):
        """Stationary time (waiting or service). Counts toward the next break/rest."""
        if minutes > 0:
            self.t += minutes
            self.idle += minutes

    def _pause(self, need: int, topup: bool) -> None:
        # Stationary time just before counts toward the pause; only the rest is inserted.
        add = max(0, need - self.idle) if topup else need
        self.t += add
        self.pause_total += add

    def drive(self, minutes: int):
        if minutes <= 0:
            return
        # Standing still long enough before driving counts as a break / rest.
        if self.idle >= REST_MIN and self.since_rest > 0:
            self.n_unverified += 1
        if self.idle >= REST_MIN and SEM["idle_counts_as_rest"]:
            self.since_rest = 0
            self.since_break = 0
        elif self.idle >= BREAK_MIN:
            self.since_break = 0
        rem = minutes
        while rem > 0:
            if self.since_rest >= REST_AFTER:
                self._pause(REST_MIN, SEM["rest_topup"])
                self.since_rest = 0
                self.since_break = 0
            elif self.since_break >= BREAK_AFTER:
                self._pause(BREAK_MIN, SEM["break_topup"])
                self.since_break = 0
            self.idle = 0
            chunk = min(rem, BREAK_AFTER - self.since_break, REST_AFTER - self.since_rest)
            self.t += chunk
            self.since_break += chunk
            self.since_rest += chunk
            self.drive_total += chunk
            rem -= chunk


def _r(x: float, nd: int = 2) -> float:
    return round(x + 0.0, nd)


def simulate(sc: Scenario, plan: dict) -> dict:
    """Return {'metrics': SimulationMetrics-like dict, 'validation': {...}, plus internals}."""
    orders = sc.order_by_id
    trucks = sc.truck_by_id
    dist = sc.dist
    violations: list[dict] = []
    owner: dict[str, str] = {}

    def viol(rule, tid, oid, msg):
        violations.append({"rule": rule, "truck": tid, "order": oid, "message": msg})

    truck_out = []
    fulfilled: dict[str, float] = {}      # order -> value factor
    order_late: dict[str, int] = {}       # order -> max late minutes over its stops
    order_late_sum: dict[str, int] = {}   # order -> summed late minutes (penalized_late_min)
    too_late: set[str] = set()
    tot_km = tot_loaded = tot_cost = tot_co2 = util_num = 0.0
    total_late_min = 0
    unverified: list[str] = []   # situations where API behaviour was never observed

    for tid, stops in plan.items():
        tr = trucks.get(tid)
        if tr is None:
            viol("unknown_truck", tid, None, f"Truck '{tid}' does not exist.")
            continue
        stops = stops or []
        picked: list[str] = []
        picked_set: set[str] = set()
        delivered: set[str] = set()
        rejected: set[str] = set()
        mismatch: set[str] = set()
        loaded_ever: set[str] = set()
        late_by_order: dict[str, list[int]] = {}
        load = 0
        max_load = 0
        pos = tr.start
        km = loaded_km = 0.0
        unum = 0.0
        clock = _Clock()
        schedule = []
        route = [tr.start_city]

        def visit(oid, action, city, window, carrying):
            nonlocal pos, km, loaded_km, unum
            d = int(dist[pos, city])
            if d > 0:
                km += d
                if carrying > 0:
                    loaded_km += d
                    unum += d * carrying / tr.capacity
                clock.drive(drive_minutes(d))
                route.append(sc.city_ids[city])
            pos = city
            arrival = clock.t
            wait = late = 0
            if window is not None:
                f, to = window
                if arrival < f:
                    wait = f - arrival
                    clock.stand(wait)
                ref = arrival if SEM["late_ref"] == "arrival" else clock.t
                late = max(0, ref - to)
            clock.stand(SERVICE_MIN)
            schedule.append({"action": action, "order": oid, "city": sc.city_ids[city],
                             "arrival_min": arrival, "wait_min": wait, "late_min": late,
                             "departure_min": clock.t})
            return late

        for st in stops:
            st = st or {}
            oid = st.get("order") or ""
            action = (st.get("action") or "").lower()
            o = orders.get(oid)
            if o is None:
                viol("unknown_order", tid, oid, f"Order '{oid}' does not exist.")
                continue
            if owner.setdefault(oid, tid) != tid:
                viol("order_assigned_multiple_times", tid, oid,
                     f"Order '{oid}' is already assigned to truck '{owner[oid]}'.")
                continue
            # API: reported at every stop of the order until it is successfully loaded.
            if o.required_type is not None and o.required_type != tr.type:
                mismatch.add(oid)
                if oid not in loaded_ever:
                    viol("truck_type_mismatch", tid, oid,
                         f"Order '{oid}' requires '{o.required_type}' truck, got '{tr.type}'.")
            if action == "pickup":
                if oid in picked_set:
                    viol("duplicate_pickup", tid, oid, f"Order '{oid}' picked up more than once.")
                    continue
                picked.append(oid)
                picked_set.add(oid)
                if load + o.weight > tr.capacity:
                    viol("capacity_exceeded", tid, oid,
                         f"Load {load + o.weight} kg would exceed capacity {tr.capacity} kg "
                         f"when picking up '{oid}'. Pickup rejected.")
                    rejected.add(oid)
                    if SEM["rejected_pickup_drives"]:
                        visit(oid, "pickup", o.p, o.pw, load)
                    continue
                late = visit(oid, "pickup", o.p, o.pw, load)
                late_by_order.setdefault(oid, []).append(late)
                loaded_ever.add(oid)
                load += o.weight
                max_load = max(max_load, load)
            elif action == "delivery":
                if oid in delivered:
                    viol("duplicate_delivery", tid, oid, f"Order '{oid}' delivered more than once.")
                    continue
                if oid not in picked_set:
                    viol("delivery_before_pickup", tid, oid, f"Order '{oid}' delivered before pickup.")
                    continue
                if oid in rejected:
                    if SEM["ignored_delivery_drives"]:
                        visit(oid, "delivery", o.d, o.dw, load)
                    continue
                delivered.add(oid)
                late = visit(oid, "delivery", o.d, o.dw, load)
                late_by_order.setdefault(oid, []).append(late)
                load -= o.weight
                if oid not in mismatch:
                    lates = late_by_order[oid]
                    ol = max(lates) if SEM["order_late"] == "max" else sum(lates)
                    order_late[oid] = ol
                    order_late_sum[oid] = sum(lates)
                    if ol > LATE_MAX:
                        too_late.add(oid)
                    else:
                        fulfilled[oid] = 1.0 - 0.5 * ol / LATE_MAX
            else:
                viol("unknown_action", tid, oid,
                     f"Unknown action '{st.get('action')}'. Use 'pickup' or 'delivery'.")
                continue

        for oid in picked:
            if oid not in delivered and oid not in rejected:
                viol("pickup_without_delivery", tid, oid,
                     f"Order '{oid}' picked up but never delivered.")

        total_late_min += sum(e["late_min"] for e in schedule)
        if clock.n_unverified:
            unverified.append(f"{tid}: stood still >= 11 h mid-day before driving (idle_counts_as_rest)")
        cost = km * tr.cost_per_km
        co2 = km * tr.co2_per_km
        tot_km += km
        tot_loaded += loaded_km
        tot_cost += cost
        tot_co2 += co2
        util_num += unum
        truck_out.append({
            "truck": tid, "route": route, "total_km": km, "loaded_km": loaded_km,
            "empty_km": km - loaded_km, "cost": cost, "co2": co2, "max_load_kg": max_load,
            "utilization": (unum / km) if km > 0 else 0.0,
            "finish_min": clock.t if schedule else 0,
            "driving_min": clock.drive_total, "break_and_rest_min": clock.pause_total,
            "schedule": schedule,
        })

    value_total = sum(o.value for o in sc.orders)
    value_fulfilled = sum(orders[o].value * f for o, f in fulfilled.items())
    value_full = sum(orders[o].value for o in fulfilled)
    n_ful = len(fulfilled)
    late_orders = [o for o in fulfilled if order_late.get(o, 0) > 0]
    n_late = len(late_orders) + (len(too_late) if SEM["orders_late_incl_too_late"] else 0)
    metrics = {
        "total_km": tot_km, "loaded_km": tot_loaded, "empty_km": tot_km - tot_loaded,
        "total_cost": tot_cost, "total_co2": tot_co2,
        "orders_fulfilled": n_ful, "orders_total": len(sc.orders),
        "value_fulfilled": value_fulfilled,
        "value_lost_to_lateness": value_full - value_fulfilled,
        "value_total": value_total,
        "truck_utilization": (util_num / tot_km) if tot_km > 0 else 0.0,
        "orders_late": n_late, "orders_too_late": len(too_late),
        "total_late_min": total_late_min,
        "penalized_late_min": sum(order_late_sum[o] for o in late_orders),
        "trucks": truck_out,
    }
    validation = {"is_valid": not violations, "violations": violations}
    return {"metrics": metrics, "validation": validation,
            "_fulfilled": fulfilled, "_unverified": unverified}


def score(sc: Scenario, plan: dict, sim: dict | None = None) -> dict:
    sim = sim or simulate(sc, plan)
    m = sim["metrics"]
    n_total = len(sc.orders)
    direct = sum(int(sc.dist[o.p, o.d]) for o in sc.orders)
    ref_km = direct * (m["orders_fulfilled"] / n_total) if n_total else 0.0
    ref_cost = ref_km * min(t.cost_per_km for t in sc.trucks)
    ref_co2 = ref_km * min(t.co2_per_km for t in sc.trucks)
    vt = m["value_total"]
    fulfillment = 100 * m["value_fulfilled"] / vt if vt else 0.0
    cost_eff = 100 * min(1.0, ref_cost / m["total_cost"]) if m["total_cost"] > 0 else 0.0
    loaded = 100 * m["loaded_km"] / m["total_km"] if m["total_km"] > 0 else 0.0
    co2_eff = 100 * min(1.0, ref_co2 / m["total_co2"]) if m["total_co2"] > 0 else 0.0
    nv = len(sim["validation"]["violations"])
    penalty = VIOLATION_PTS * nv
    late_penalty = 10 * 0.5 * 100 * m["value_lost_to_lateness"] / vt if vt else 0.0
    s = 10 * (0.5 * fulfillment + 0.2 * cost_eff + 0.15 * loaded + 0.15 * co2_eff) - penalty
    return {
        "scenario": sc.id, "score": s,
        "breakdown": {"fulfillment": fulfillment, "cost_efficiency": cost_eff,
                      "loaded_ratio": loaded, "co2_efficiency": co2_eff,
                      "penalty": penalty, "late_penalty": late_penalty},
        "metrics": m, "validation": sim["validation"],
        "_unverified": sim["_unverified"],
    }


# Decimal places the API uses when returning these fields (observed).
_ROUND = {"score": 2, "fulfillment": 2, "cost_efficiency": 2, "loaded_ratio": 2,
          "co2_efficiency": 2, "late_penalty": 2, "penalty": 2,
          "total_cost": 2, "total_co2": 2, "cost": 2, "co2": 2,
          "truck_utilization": 4, "utilization": 4,
          "value_fulfilled": 4, "value_lost_to_lateness": 4, "value_total": 4}


def api_round(x, key=None):
    """Return a copy of a simulate/score result rounded the way the API returns it."""
    if isinstance(x, dict):
        return {k: api_round(v, k) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, list):
        return [api_round(v) for v in x]
    if isinstance(x, float) and key in _ROUND:
        return round(x, _ROUND[key])
    return x
