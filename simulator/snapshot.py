"""Download scenario data and save it as a timestamped snapshot under data/<scenario>/<ts>/."""
from __future__ import annotations

import json
import time

from . import config
from .api import Client


def download(sid: str, client: Client | None = None) -> str:
    c = client or Client()
    ts = time.strftime("%Y%m%d_%H%M%S")
    d = config.DATA_DIR / sid / ts
    d.mkdir(parents=True, exist_ok=True)
    parts = {
        "cities": c.cities(sid),
        "trucks": c.trucks(sid),
        "orders": c.orders(sid),
        "distance_matrix": c.distance_matrix(sid),
        "sample_plan": c.sample_plan(sid),
    }
    for name, obj in parts.items():
        (d / f"{name}.json").write_text(json.dumps(obj, indent=1))
    (d / "distance_matrix.csv").write_text(c.distance_matrix_csv(sid))
    # Skip saving if identical to latest previous snapshot? Keep all; cheap.
    return str(d)


def download_all(client: Client | None = None) -> list[str]:
    c = client or Client()
    scen = c.scenarios()
    (config.DATA_DIR).mkdir(exist_ok=True)
    (config.DATA_DIR / f"scenarios_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(
        json.dumps(scen, indent=1))
    ids = [s["id"] if isinstance(s, dict) else s for s in scen]
    return [download(i, c) for i in ids]
