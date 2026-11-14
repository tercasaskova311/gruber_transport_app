"""
evaluator.py — the solver's local referee.

    simulate_truck(inst, k, route) -> TruckResult     (one truck, exact rules)
    score(inst, totals)            -> (S, components) (the official formula)

The solver only ever calls these two functions. When Part B's sim.py passes the
parity tests against the official /Simulate, swap these two functions for B's
(same signatures) and nothing else changes.

Every rule the documentation leaves open is a named constant below, marked ⚠.
Test each one against /Simulate on small/middle/big and set it accordingly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from instance import Instance

# ---------------- official constants (spec §8.1) ----------------
SPEED_KMH = 70
SERVICE_MIN = 30
BREAK_AFTER_MIN = 270          # 4.5 h driving
BREAK_MIN = 45
REST_AFTER_MIN = 540           # 9 h driving
REST_MIN = 660                 # 11 h
LATE_GRACE_MIN = 60            # up to 60 min late = still fulfilled
LATE_MIN_FACTOR = 0.5          # value at 60 min late

# ---------------- time rules, verified against /Simulate (see docs/semantics.md) ----------------
# - driving minutes = ceil(km * 60 / 70) per leg; a break/rest may interrupt a leg
# - "idle" = minutes standing still (waiting + service) since the truck last drove, summed
#   over consecutive same-city stops. Idle >= 45 before driving resets the 4.5 h counter.
#   When a break/rest is due, only the missing part (45 - idle, 660 - idle) is inserted.
# - lateness = arrival - to; an order late at both stops counts the larger lateness.

# ---------------- optional realism (NOT in the official score) ----------------
# The official score has no planning horizon, so a truck may get a 3-week route.
# Set e.g. 7*24*60 to cap every route at one week for a more realistic demo plan.
MAX_FINISH_MIN: float | None = None


@dataclass(slots=True)
class TruckResult:
    km: float = 0.0
    loaded_km: float = 0.0
    cost: float = 0.0
    co2: float = 0.0
    value: float = 0.0              # value fulfilled, after late decay
    n_fulfilled: int = 0
    feasible: bool = True           # False = capacity breach, precedence error or >60 min late
    finish_min: float = 0.0
    drive_min: float = 0.0
    break_rest_min: float = 0.0
    load_km: float = 0.0            # Σ load × km (for utilisation)
    max_load: float = 0.0
    late: dict = field(default_factory=dict)   # order idx -> minutes late (only if > 0)
    states: list | None = None      # state after each stop (for resuming), if recorded
    stop_late: list | None = None   # lateness at each stop, if recorded
    late_stops: list | None = None  # (stop index, order, minutes late) for late stops, if recorded


@dataclass(slots=True)
class Totals:
    km: float = 0.0
    loaded_km: float = 0.0
    cost: float = 0.0
    co2: float = 0.0
    value: float = 0.0
    n_fulfilled: int = 0

    def add(self, r: TruckResult, sign: int = 1) -> None:
        self.km += sign * r.km
        self.loaded_km += sign * r.loaded_km
        self.cost += sign * r.cost
        self.co2 += sign * r.co2
        self.value += sign * r.value
        self.n_fulfilled += sign * r.n_fulfilled

    def copy(self) -> "Totals":
        return Totals(self.km, self.loaded_km, self.cost, self.co2, self.value, self.n_fulfilled)

    def swapped(self, old: TruckResult, new: TruckResult) -> "Totals":
        """Totals if one truck's result `old` is replaced by `new` (no mutation)."""
        return Totals(self.km - old.km + new.km,
                      self.loaded_km - old.loaded_km + new.loaded_km,
                      self.cost - old.cost + new.cost,
                      self.co2 - old.co2 + new.co2,
                      self.value - old.value + new.value,
                      self.n_fulfilled - old.n_fulfilled + new.n_fulfilled)


EMPTY = TruckResult()
INFEASIBLE = TruckResult(feasible=False)


def simulate_truck(inst: Instance, k: int, route: list[tuple[bool, int]], early_exit: bool = True,
                   base: TruckResult | None = None, start: int = 0, record: bool = False,
                   stop: int | None = None) -> TruckResult:
    """Simulate one truck. route = [(is_pickup, order_idx), ...] in visiting order.

    early_exit=True  stop at the first broken rule (fast; used by the search)
    early_exit=False simulate everything (used for reporting)
    base, start      resume from base.states[start] (state after the first `start` stops of a
                     route whose first `start` stops are identical). Exact, just faster.
                     base must have been simulated with record=True. Pickup-before-delivery is
                     only checked in a full simulation (base=None): callers that resume must
                     build routes with the pickup first (the search always does).
    record           store the state after every stop (so later insertions can resume)
    stop             simulate the clock only for the first `stop` stops; the rest of the route
                     must be identical to the end of base's route, start in the same city with
                     the same load, and contain no time-window stop. Its km are then taken from
                     base. Everything the score uses (km, loaded km, cost, CO2, value, fulfilled)
                     is exact; finish_min, drive_min and break_rest_min are NOT (clock stopped
                     early), so such a result must not be stored as the route's state.
    """
    if not route:
        return EMPTY
    t = inst.trucks[k]
    D = inst.D
    M = inst.M
    orders = inst.orders
    late: dict[int, float] = {}
    picked: set[int] = set()
    stop_late: list[float] = []
    late_stops: list = []
    if base is not None and start > 0 and base.states:
        (city, now, sb, sr, brk, idle, load, km, loaded_km, load_km, max_load, drive_total) = base.states[start]
        for j, oi, lm in base.late_stops:
            if j >= start:
                break
            if lm > late.get(oi, 0.0):
                late[oi] = lm
        if record:
            stop_late = base.stop_late[:start]
            late_stops = [x for x in base.late_stops if x[0] < start]
        i0 = start
        check = False
    else:
        city = t.start
        now = sb = sr = brk = 0.0              # clock, since break, since rest, break+rest total
        idle = 0.0                             # standing still since last drive
        load = km = loaded_km = load_km = max_load = 0.0
        drive_total = 0
        i0 = 0
        check = True
    states = None
    if record:
        states = base.states[:start + 1] if (base is not None and start > 0 and base.states) else \
            [(city, now, sb, sr, brk, idle, load, km, loaded_km, load_km, max_load, drive_total)]
    feasible = True
    cap_kg = t.capacity + 1e-9

    n_sim = len(route) if stop is None or stop >= len(route) else stop
    for idx in range(i0, n_sim):
        is_p, oi = route[idx]
        o = orders[oi]
        dest = o.p if is_p else o.d
        d = D[city][dest]
        if d > 0:
            km += d
            if load > 0:
                loaded_km += d
                load_km += load * d
            rem = M[city][dest]
            drive_total += rem
            # standing still long enough before driving counts as a rest / break
            if idle >= REST_MIN:                # unverified (unreachable with current data)
                sb = sr = 0
            elif idle >= BREAK_MIN:
                sb = 0
            # drive, inserting breaks / rests; standing time counts toward the pause
            while rem > 0:
                if sr >= REST_AFTER_MIN:
                    add = REST_MIN - idle if idle < REST_MIN else 0
                    now += add; brk += add; sb = 0; sr = 0
                elif sb >= BREAK_AFTER_MIN:
                    add = BREAK_MIN - idle if idle < BREAK_MIN else 0
                    now += add; brk += add; sb = 0
                idle = 0
                cap = BREAK_AFTER_MIN - sb
                if REST_AFTER_MIN - sr < cap:
                    cap = REST_AFTER_MIN - sr
                if rem < cap:
                    cap = rem
                now += cap; sb += cap; sr += cap; rem -= cap
            city = dest
        arrival = now
        tw = o.ptw if is_p else o.dtw
        wait = 0.0
        lm = 0.0
        if tw is not None:
            a, b = tw
            if arrival < a:
                wait = a - arrival
                now = a
            ref = arrival
            if ref > b:
                lm = ref - b
                if lm > LATE_GRACE_MIN and early_exit:
                    return INFEASIBLE
                if lm > late.get(oi, 0.0):
                    late[oi] = lm
        now += SERVICE_MIN
        idle += wait + SERVICE_MIN          # adds up over same-city stops (no driving between)
        if is_p:
            load += o.weight
            if check:
                picked.add(oi)
            if load > cap_kg:
                if early_exit:
                    return INFEASIBLE
                feasible = False
            if load > max_load:
                max_load = load
        else:
            if check and oi not in picked:
                if early_exit:
                    return INFEASIBLE
                feasible = False
            load -= o.weight
        if record:
            stop_late.append(lm)
            if lm > 0:
                late_stops.append((idx, oi, lm))
            states.append((city, now, sb, sr, brk, idle, load, km, loaded_km, load_km, max_load, drive_total))

    if n_sim < len(route):
        # tail: same legs and loads as the end of base's route, no time windows -> only km matter
        bs = base.states
        b0 = bs[n_sim - (len(route) - len(bs) + 1)]
        b1 = bs[-1]
        km += b1[7] - b0[7]
        loaded_km += b1[8] - b0[8]
        load_km += b1[9] - b0[9]
        if b1[10] > max_load:
            max_load = b1[10]

    if MAX_FINISH_MIN is not None and now > MAX_FINISH_MIN:
        if early_exit:
            return INFEASIBLE
        feasible = False

    value = 0.0
    n_f = 0
    if late:
        for is_p, oi in route:
            if not is_p:
                continue
            lm = late.get(oi, 0.0)
            if lm > LATE_GRACE_MIN:
                feasible = False            # never accept "too late" inside the search
                continue
            f = 1.0 - (1.0 - LATE_MIN_FACTOR) * lm / LATE_GRACE_MIN if lm > 0 else 1.0
            value += orders[oi].value * f
            n_f += 1
    else:
        for is_p, oi in route:
            if is_p:
                value += orders[oi].value
                n_f += 1

    return TruckResult(km, loaded_km, km * t.cost_per_km, km * t.co2_per_km, value, n_f, feasible,
                       now, float(drive_total), brk, load_km, max_load, late,
                       states if record else None, stop_late if record else None,
                       late_stops if record else None)


def score(inst: Instance, tot: Totals) -> tuple[float, dict]:
    """Official score (spec §9), no violations (the solver never creates any)."""
    F = 100.0 * tot.value / inst.value_total if inst.value_total else 0.0
    ref_km = inst.direct_km_total * tot.n_fulfilled / inst.n_orders if inst.n_orders else 0.0
    ref_cost = ref_km * inst.min_cost_per_km
    ref_co2 = ref_km * inst.min_co2_per_km
    C = 100.0 * min(1.0, ref_cost / tot.cost) if tot.cost > 0 else 0.0
    E = 100.0 * min(1.0, ref_co2 / tot.co2) if tot.co2 > 0 else 0.0
    L = 100.0 * tot.loaded_km / tot.km if tot.km > 0 else 0.0
    S = 10.0 * (0.50 * F + 0.20 * C + 0.15 * L + 0.15 * E)
    return S, {"fulfillment": F, "cost_eff": C, "loaded_ratio": L, "co2_eff": E,
               "ref_cost": ref_cost, "ref_co2": ref_co2}


def score_value(inst: Instance, tot: Totals) -> float:
    if inst.value_only:
        return 1000.0 * tot.value / inst.value_total - inst.km_weight * tot.km
    return score(inst, tot)[0]


def score_swapped(inst: Instance, tot: Totals, old: TruckResult, new: TruckResult) -> float:
    """score_value(inst, tot.swapped(old, new)) without building objects (same arithmetic)."""
    km = tot.km - old.km + new.km
    if inst.value_only:
        return 1000.0 * (tot.value - old.value + new.value) / inst.value_total - inst.km_weight * km
    cost = tot.cost - old.cost + new.cost
    co2 = tot.co2 - old.co2 + new.co2
    n = inst.n_orders
    F = 100.0 * (tot.value - old.value + new.value) / inst.value_total if inst.value_total else 0.0
    ref_km = inst.direct_km_total * (tot.n_fulfilled - old.n_fulfilled + new.n_fulfilled) / n if n else 0.0
    C = 100.0 * min(1.0, ref_km * inst.min_cost_per_km / cost) if cost > 0 else 0.0
    E = 100.0 * min(1.0, ref_km * inst.min_co2_per_km / co2) if co2 > 0 else 0.0
    L = 100.0 * (tot.loaded_km - old.loaded_km + new.loaded_km) / km if km > 0 else 0.0
    return 10.0 * (0.50 * F + 0.20 * C + 0.15 * L + 0.15 * E)
