"""
instance.py — load a scenario into fast, index-based Python structures.

Expected folder layout (what fetch.py should save, one JSON per API endpoint):
    <scenario_dir>/cities.json            GET /Scenarios/{id}/Cities
    <scenario_dir>/trucks.json            GET /Scenarios/{id}/Trucks
    <scenario_dir>/orders.json            GET /Scenarios/{id}/Orders
    <scenario_dir>/distance_matrix.json   GET /Scenarios/{id}/DistanceMatrix

Everything is converted to integer indices so the solver can use plain lists
(much faster than dict lookups or numpy scalars inside tight loops).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------
# Order value rules (spec §9.1) — used only if the API does not send "value".
# --------------------------------------------------------------------------
BASE_VALUE = {None: 1.0, "standard": 1.0, "refrigerated": 1.5, "hazmat": 1.5}
TIME_WINDOW_BONUS = 0.5

# A generic "time_window" field (no pickup/delivery prefix) is applied here.
# ⚠ ASSUMPTION — check the real JSON on day 1 and adjust.
GENERIC_WINDOW_APPLIES_TO = "delivery"


@dataclass
class Truck:
    idx: int
    id: str
    start: int          # city index
    capacity: float
    type: str
    cost_per_km: float
    co2_per_km: float


@dataclass
class Order:
    idx: int
    id: str
    p: int              # pickup city index
    d: int              # delivery city index
    weight: float
    required_type: Optional[str]
    value: float
    ptw: Optional[tuple[float, float]] = None   # pickup window (from, to) in minutes
    dtw: Optional[tuple[float, float]] = None   # delivery window (from, to) in minutes


@dataclass
class Instance:
    city_ids: list[str]
    city_names: list[str]
    lat: list[float]
    lon: list[float]
    D: list[list[float]]                         # km, D[i][j]
    trucks: list[Truck]
    orders: list[Order]
    # precomputed
    compatible: list[list[int]] = field(default_factory=list)   # order -> truck indices
    direct_km: list[float] = field(default_factory=list)
    value_total: float = 0.0
    direct_km_total: float = 0.0
    min_cost_per_km: float = 0.0
    min_co2_per_km: float = 0.0
    # sub-problems (twfirst.py): judge plans by value served minus a small km penalty, not by the score
    value_only: bool = False
    km_weight: float = 0.0
    M: list[list[int]] = field(default_factory=list)   # driving minutes, ceil(km * 60 / 70)

    @property
    def n_orders(self) -> int:
        return len(self.orders)


# --------------------------------------------------------------------------
def _parse_window(raw) -> Optional[tuple[float, float]]:
    """Accept {"from": a, "to": b} / {"start","end"} / {"earliest","latest"} / [a, b]."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        a, b = raw
    elif isinstance(raw, dict):
        a = next((raw[k] for k in ("from", "start", "earliest", "from_min") if k in raw), None)
        b = next((raw[k] for k in ("to", "end", "latest", "to_min") if k in raw), None)
        if a is None and b is None:
            return None
    else:
        raise ValueError(f"Unrecognised time-window format: {raw!r}")
    if not all(isinstance(x, (int, float)) or x is None for x in (a, b)):
        raise ValueError(
            f"Time window {raw!r} is not in minutes. Convert it in instance._parse_window "
            "(minute 0 = Day 1, 06:00)."
        )
    return (float(a) if a is not None else 0.0, float(b) if b is not None else float("inf"))


def _windows_of(o: dict) -> tuple[Optional[tuple], Optional[tuple]]:
    ptw = dtw = None
    for k in ("pickup_window", "pickup_time_window", "pickup_tw"):
        if o.get(k) is not None:
            ptw = _parse_window(o[k])
    for k in ("delivery_window", "delivery_time_window", "delivery_tw"):
        if o.get(k) is not None:
            dtw = _parse_window(o[k])
    if o.get("time_window") is not None:
        w = _parse_window(o["time_window"])
        target = (o["time_window"].get("applies_to") if isinstance(o["time_window"], dict) else None) \
            or GENERIC_WINDOW_APPLIES_TO
        if target == "pickup":
            ptw = w
        else:
            dtw = w
    return ptw, dtw


def load_instance(folder: str | Path) -> Instance:
    folder = Path(folder)
    cities = json.loads((folder / "cities.json").read_text(encoding="utf-8"))
    trucks_raw = json.loads((folder / "trucks.json").read_text(encoding="utf-8"))
    orders_raw = json.loads((folder / "orders.json").read_text(encoding="utf-8"))
    dm = json.loads((folder / "distance_matrix.json").read_text(encoding="utf-8"))

    city_ids = [c["id"] for c in cities]
    cidx = {cid: i for i, cid in enumerate(city_ids)}
    D = [[float(dm[a][b]) for b in city_ids] for a in city_ids]

    trucks = [
        Truck(i, t["id"], cidx[t["start_city"]], float(t["capacity_kg"]), t.get("type", "standard"),
              float(t["cost_per_km"]), float(t["co2_per_km"]))
        for i, t in enumerate(trucks_raw)
    ]

    orders = []
    for i, o in enumerate(orders_raw):
        ptw, dtw = _windows_of(o)
        req = o.get("required_truck_type")
        value = o.get("value")
        if value is None:
            value = BASE_VALUE.get(req, 1.0) + (TIME_WINDOW_BONUS if (ptw or dtw) else 0.0)
        orders.append(Order(i, o["id"], cidx[o["pickup_city"]], cidx[o["delivery_city"]],
                            float(o["weight_kg"]), req, float(value), ptw, dtw))

    inst = Instance(city_ids, [c.get("name", c["id"]) for c in cities],
                    [c.get("latitude", 0.0) for c in cities], [c.get("longitude", 0.0) for c in cities],
                    D, trucks, orders)
    precompute(inst)
    return inst


def precompute(inst: Instance) -> None:
    inst.compatible = [
        [t.idx for t in inst.trucks
         if (o.required_type is None or t.type == o.required_type) and o.weight <= t.capacity]
        for o in inst.orders
    ]
    inst.M = [[math.ceil(d * 60 / 70) for d in row] for row in inst.D]
    inst.direct_km = [inst.D[o.p][o.d] for o in inst.orders]
    inst.value_total = sum(o.value for o in inst.orders)
    inst.direct_km_total = sum(inst.direct_km)
    inst.min_cost_per_km = min(t.cost_per_km for t in inst.trucks)
    inst.min_co2_per_km = min(t.co2_per_km for t in inst.trucks)
