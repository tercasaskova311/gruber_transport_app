"""Single entry point for scenario data. Swap the backend here (e.g. a database)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config


@dataclass
class Truck:
    id: str
    idx: int
    start_city: str
    start: int          # city index
    capacity: int
    type: str
    cost_per_km: float
    co2_per_km: float


@dataclass
class Order:
    id: str
    idx: int
    pickup_city: str
    delivery_city: str
    p: int              # pickup city index
    d: int              # delivery city index
    weight: int
    required_type: str | None
    pw: tuple[int, int] | None   # pickup window (from, to)
    dw: tuple[int, int] | None   # delivery window (from, to)
    value: float


@dataclass
class Scenario:
    id: str
    snapshot: str
    city_ids: list[str]
    city_index: dict[str, int]
    dist: np.ndarray            # int km, [n_cities, n_cities]
    trucks: list[Truck]
    orders: list[Order]
    truck_by_id: dict[str, Truck] = field(default_factory=dict)
    order_by_id: dict[str, Order] = field(default_factory=dict)
    sample_plan: dict | None = None
    cities_raw: list[dict] | None = None

    def __post_init__(self):
        self.truck_by_id = {t.id: t for t in self.trucks}
        self.order_by_id = {o.id: o for o in self.orders}


def _win(w):
    return None if not w else (int(w["from"]), int(w["to"]))


def from_raw(sid: str, cities: list, trucks: list, orders: list, dm: dict,
             sample_plan: dict | None = None, snapshot: str = "") -> Scenario:
    city_ids = list(dm.keys())
    ci = {c: i for i, c in enumerate(city_ids)}
    n = len(city_ids)
    dist = np.zeros((n, n), dtype=np.int64)
    for a, row in dm.items():
        for b, v in row.items():
            dist[ci[a], ci[b]] = v
    ts = [Truck(t["id"], i, t["start_city"], ci[t["start_city"]], int(t["capacity_kg"]),
                t["type"], float(t["cost_per_km"]), float(t["co2_per_km"]))
          for i, t in enumerate(trucks)]
    os_ = [Order(o["id"], i, o["pickup_city"], o["delivery_city"], ci[o["pickup_city"]],
                 ci[o["delivery_city"]], int(o["weight_kg"]), o.get("required_truck_type"),
                 _win(o.get("pickup_window")), _win(o.get("delivery_window")),
                 float(o["value"]))
           for i, o in enumerate(orders)]
    return Scenario(sid, snapshot, city_ids, ci, dist, ts, os_, sample_plan=sample_plan,
                    cities_raw=cities)


def list_snapshots(sid: str) -> list[Path]:
    d = config.DATA_DIR / sid
    if not d.exists():
        return []
    # names: 20261113_192945 (old) or 20261113T203436220952Z (database); sort by the digits
    key = lambda p: "".join(ch for ch in p.name if ch.isdigit()).ljust(20, "0")
    return sorted((p for p in d.iterdir() if p.is_dir() and (p / "orders.json").exists()), key=key)


def load(sid: str, snapshot: str | None = None) -> Scenario:
    """Load a scenario snapshot (latest by default) from data/<sid>/<ts>/."""
    if snapshot:
        p = Path(snapshot)
        if not p.is_absolute():
            p = config.DATA_DIR / sid / snapshot
    else:
        snaps = list_snapshots(sid)
        if not snaps:
            raise FileNotFoundError(f"no snapshot for {sid}; run `cd data_layer && ./run_all.sh`")
        p = snaps[-1]
    rd = lambda n: json.loads((p / f"{n}.json").read_text())
    sp = rd("sample_plan") if (p / "sample_plan.json").exists() else None
    return from_raw(sid, rd("cities"), rd("trucks"), rd("orders"), rd("distance_matrix"),
                    sp, snapshot=p.name)
