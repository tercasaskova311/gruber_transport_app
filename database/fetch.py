"""fetch.py : pull the Gruber API into DuckDB as an append-only snapshot.

    python fetch.py                     # fetch once (only if data changed), then prepare + checks
    python fetch.py --force             # new snapshot even if nothing changed
    python fetch.py --scenario 3        # only scenario 3 (repeatable)
    python fetch.py --watch --every 5   # loop forever, every 5 minutes
    python fetch.py --watch --on-change "python solver.py"   # run a command after each new snapshot

Change detection: sha256 of /Scenarios + every selected scenario's /Cities.
If it equals the fingerprint of the latest snapshot, nothing is written.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone

import duckdb

try:
    from . import config as C
except ImportError:  # run as a script from data_layer/ (python fetch.py)
    import config as C


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def get_text(path):
    url = C.BASE_URL + path
    for attempt in range(1, C.HTTP_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "*/*", "User-Agent": "noi-hackathon-data-layer"})
            with urllib.request.urlopen(req, timeout=C.HTTP_TIMEOUT_S) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:  # network error, 5xx, timeout...
            if attempt == C.HTTP_RETRIES:
                raise RuntimeError(f"GET {url} failed after {attempt} attempts: {e}") from e
            wait = 2 ** attempt
            log(f"GET {path} failed ({e}); retry {attempt}/{C.HTTP_RETRIES - 1} in {wait}s")
            time.sleep(wait)


def get_json(path):
    return json.loads(get_text(path))


# ---------------------------------------------------------------------------
# Tolerant field access: "start_city", "startCity", "StartCity" all match.
# ---------------------------------------------------------------------------
def _norm(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def pick(d, *names, default=None):
    nd = {_norm(k): v for k, v in d.items()}
    for n in names:
        v = nd.get(_norm(n))
        if v is not None:
            return v
    return default


def _id(v):
    return None if v is None else str(v)


def _words(key):
    """'pickupTimeWindowFrom' -> ['pickup','time','window','from'];  'delivery_tw_to' -> [...,'tw','to']"""
    return [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", str(key))]


# ===========================================================================
# >>> TIME WINDOW MAPPING — the one place to adjust once you see real JSON <<<
#
# Output: minutes since Day 1 06:00 for
#     pickup_tw_from, pickup_tw_to, delivery_tw_from, delivery_tw_to   (None = no limit)
#
# The parser walks the whole order JSON and handles shapes like
#     {"pickup_tw_from": 120, "pickup_tw_to": 300}
#     {"pickupTimeWindow": {"from": "2026-11-14T08:00:00", "to": "..."}}
#     {"timeWindows": [{"type": "Delivery", "start": "1.08:00:00", "end": "1.12:00:00"}]}
#     {"delivery_window": [600, 720]}
# Values: int/float = already minutes since minute 0; ISO datetime = relative
# to Day 1 06:00 (Day 1 = earliest date seen in the scenario, or DAY1_DATE);
# "HH:MM[:SS]" = clock time on Day 1; "D.HH:MM:SS" (.NET TimeSpan) = D days later.
#
# If the real API looks different, the fastest fix is usually to replace the
# body of parse_time_windows() with 4 explicit lines, e.g.
#     tw = order["timeWindow"]
#     return {"pickup_tw_from": None, "pickup_tw_to": None,
#             "delivery_tw_from": to_minutes(tw["from"], day1), "delivery_tw_to": to_minutes(tw["to"], day1)}
# ===========================================================================
TW_COLS = ("pickup_tw_from", "pickup_tw_to", "delivery_tw_from", "delivery_tw_to")
DAY1_DATE = None                 # e.g. date(2026, 11, 14) to pin Day 1; None = infer per scenario
UNSIDED_DEFAULT = "delivery"     # a window that doesn't say pickup/delivery is assumed to be this
NUMBERS_ARE = "minutes"          # or "hours" if the API sends 2.5 meaning 2h30 after minute 0

TIMEISH = {"window", "windows", "tw", "time", "timewindow", "slot"}
FROM_WORDS = {"from", "start", "earliest", "open", "opening", "begin", "ready", "min", "after"}
TO_WORDS = {"to", "end", "latest", "close", "closing", "until", "due", "max", "before"}
PICKUP_WORDS = {"pickup", "pick", "loading", "load", "origin", "collection"}
DELIVERY_WORDS = {"delivery", "deliver", "dropoff", "drop", "unload", "unloading", "destination"}


def _side(words):
    ws = set(words)
    if ws & PICKUP_WORDS:
        return "pickup"
    if ws & DELIVERY_WORDS:
        return "delivery"
    return None


def _side_from_type_field(d):
    """{'type': 'Pickup', ...} -> 'pickup'."""
    for k, v in d.items():
        if isinstance(v, str) and set(_words(k)) & {"type", "kind", "side", "stop", "for", "location"}:
            s = _side(_words(v))
            if s:
                return s
    return None


def _bound(words):
    ws = set(words)
    if ws & FROM_WORDS:
        return "from"
    if ws & TO_WORDS:
        return "to"
    return None


def _tw_leaves(obj, side=None, timeish=False):
    """Yield (side, 'from'|'to', raw_value) for everything that looks like a window bound."""
    for key, val in obj.items():
        kw = _words(key)
        s = _side(kw) or side
        t = timeish or bool(set(kw) & TIMEISH)
        if isinstance(val, dict):
            yield from _tw_leaves(val, s or _side_from_type_field(val), t)
        elif isinstance(val, list):
            if t and len(val) == 2 and not any(isinstance(x, (dict, list)) for x in val):
                yield (s or UNSIDED_DEFAULT), "from", val[0]
                yield (s or UNSIDED_DEFAULT), "to", val[1]
            for item in val:
                if isinstance(item, dict):
                    yield from _tw_leaves(item, s or _side_from_type_field(item), t)
        else:
            b = _bound(kw)
            if b and (t or s):
                yield (s or UNSIDED_DEFAULT), b, val


def to_minutes(v, day1=None):
    """Any time-ish value -> int minutes since Day 1 06:00 (or None)."""
    if v is None or isinstance(v, bool) or v == "":
        return None
    if isinstance(v, (int, float)):
        return round(v * 60) if NUMBERS_ARE == "hours" else round(v)
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return to_minutes(float(s), day1)
    m = re.fullmatch(r"(?:(\d+)\.)?(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?", s)
    if m:  # "08:30", "1.08:30:00"
        days, h, mi = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
        return days * 1440 + h * 60 + mi - C.DAY1_START_HOUR * 60
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise ValueError(f"Don't know how to read time value {v!r}: adjust to_minutes() in fetch.py")
    d1 = DAY1_DATE or day1 or dt.date()
    start = datetime.combine(d1, dtime(C.DAY1_START_HOUR))
    return round((dt - start).total_seconds() / 60)


def guess_day1(orders_raw):
    """Earliest ISO date mentioned anywhere in the orders (None if no ISO dates)."""
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", json.dumps(orders_raw))
    return min(date.fromisoformat(d) for d in dates) if dates else None


def parse_time_windows(order, day1=None):
    out = dict.fromkeys(TW_COLS)
    for side, bound, raw in _tw_leaves(order, _side_from_type_field(order)):
        col = f"{side}_tw_{bound}"
        val = to_minutes(raw, day1)
        if val is not None and out[col] is None:
            out[col] = val
    return out
# ===========================================================================


def parse_distance_csv(text):
    """Wide CSV (city_id,C001,C002,...) -> list of (from_city, to_city, km)."""
    rows = list(csv.reader(io.StringIO(text)))
    header = [h.strip() for h in rows[0][1:]]
    out = []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        frm = r[0].strip()
        for to, km in zip(header, r[1:]):
            out.append((frm, to, float(km) if km.strip() else None))
    return out


def distance_dict(text):
    """Wide CSV -> {from: {to: km}}, the shape of GET /DistanceMatrix (whole km stay ints)."""
    out = {}
    for frm, to, km in parse_distance_csv(text):
        out.setdefault(frm, {})[to] = int(km) if km is not None and km == int(km) else km
    return out


# ---------------------------------------------------------------------------
# Snapshot logic
# ---------------------------------------------------------------------------
def init_schema(con):
    _migrate_old_results(con)
    con.execute((C.HERE / "schema.sql").read_text())


def _migrate_old_results(con):
    """results.runs from before the API-shaped layout (no plan_hash column): drop it if
    empty, otherwise keep it as results.*_legacy. Safe to call every time."""
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'results' AND table_name = 'runs'").fetchall()}
    if not cols or "plan_hash" in cols:
        return
    n = con.execute("SELECT count(*) FROM results.runs").fetchone()[0]
    for t in ("run_stops", "runs"):
        if n == 0:
            con.execute(f"DROP TABLE IF EXISTS results.{t}")
        else:
            con.execute(f"ALTER TABLE IF EXISTS results.{t} RENAME TO {t}_legacy")
    log(f"results.runs had the old layout ({n} rows) -> {'dropped' if n == 0 else 'renamed to *_legacy'}")


def fingerprint(scenarios, cities_by_sid):
    blob = json.dumps({"scenarios": scenarios, "cities": cities_by_sid}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def fetch_snapshot(con, only=None, force=False):
    """Returns the new snapshot_id, or None if nothing changed."""
    scenarios = get_json(C.URL_SCENARIOS)
    if only:
        scenarios = [s for s in scenarios if str(pick(s, "id")) in only]
        if not scenarios:
            raise SystemExit(f"No scenario matches {only}")
    sids = [str(pick(s, "id")) for s in scenarios]
    cities = {sid: get_json(C.URL_CITIES.format(sid=sid)) for sid in sids}
    fp = fingerprint(scenarios, cities)

    last = dict(con.execute(
        f"SELECT scenario_id, fingerprint FROM raw.cur_snapshots WHERE scenario_id IN ({','.join('?' * len(sids))})",
        sids).fetchall())
    if not force and all(last.get(sid) == fp for sid in sids):
        log(f"unchanged ({len(sids)} scenarios, fingerprint {fp[:10]})")
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    snap = now.strftime("%Y%m%dT%H%M%S%fZ")
    log(f"change detected -> new snapshot {snap}")

    # 1) download everything first (no DB writes yet)
    payload = {}
    for s in scenarios:
        sid = str(pick(s, "id"))
        folder = C.DATA_DIR / sid / snap   # same layout as gruber.loader reads
        folder.mkdir(parents=True, exist_ok=True)
        trucks = get_json(C.URL_TRUCKS.format(sid=sid))
        orders = get_json(C.URL_ORDERS.format(sid=sid))
        dist_csv = get_text(C.URL_DISTANCES.format(sid=sid))
        for name, obj in (("scenario", s), ("cities", cities[sid]), ("trucks", trucks), ("orders", orders)):
            (folder / f"{name}.json").write_text(json.dumps(obj, indent=1))
        (folder / "distances.csv").write_text(dist_csv)
        (folder / "distance_matrix.json").write_text(json.dumps(distance_dict(dist_csv)))  # for the JSON loaders
        payload[sid] = (s, cities[sid], trucks, orders, dist_csv, folder)
        log(f"  scenario {sid}: {len(cities[sid])} cities, {len(trucks)} trucks, {len(orders)} orders")
    (C.DATA_DIR / f"scenarios_{snap}.json").write_text(json.dumps(scenarios, indent=1))

    # 2) write all rows in ONE transaction; snapshots row goes in last
    con.execute("BEGIN")
    try:
        for sid, (s, cities_j, trucks, orders, dist_csv, folder) in payload.items():
            key = (snap, sid)
            con.executemany("INSERT INTO raw.cities VALUES (?,?,?,?,?,?,?,?)", [
                key + (_id(pick(c, "id")), pick(c, "name"), pick(c, "country"),
                       pick(c, "latitude", "lat"), pick(c, "longitude", "lon", "lng"), json.dumps(c))
                for c in cities_j])
            con.executemany("INSERT INTO raw.trucks VALUES (?,?,?,?,?,?,?,?,?)", [
                key + (_id(pick(t, "id")), _id(pick(t, "start_city", "start_city_id", "startCityId", "depot")),
                       pick(t, "capacity_kg", "capacity"), pick(t, "type", "truck_type"),
                       pick(t, "cost_per_km"), pick(t, "co2_per_km", "emissions_per_km"), json.dumps(t))
                for t in trucks])
            day1 = guess_day1(orders)
            rows = []
            for o in orders:
                tw = parse_time_windows(o, day1)
                req = pick(o, "required_truck_type", "requiredTruckType", "truck_type")
                rows.append(key + (
                    _id(pick(o, "id")),
                    _id(pick(o, "pickup_city", "pickup_city_id", "pickupCityId", "origin")),
                    _id(pick(o, "delivery_city", "delivery_city_id", "deliveryCityId", "destination")),
                    pick(o, "weight_kg", "weight"),
                    (str(req).lower() if req not in (None, "", "none", "None") else None),
                    pick(o, "value"),
                    *(tw[c] for c in TW_COLS),
                    json.dumps(o)))
            con.executemany("INSERT INTO raw.orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

            long_csv = folder / "distances_long.csv"
            with long_csv.open("w", newline="") as f:
                csv.writer(f).writerows(parse_distance_csv(dist_csv))
            path = str(long_csv).replace("'", "''")
            con.execute(f"""
                INSERT INTO raw.distances
                SELECT ?, ?, from_city, to_city, km
                FROM read_csv('{path}', header=false,
                     columns={{'from_city':'VARCHAR','to_city':'VARCHAR','km':'DOUBLE'}})""", list(key))

            con.execute("INSERT INTO raw.snapshots VALUES (?,?,?,?,?,?,?,?)", [
                snap, sid, now, fp, pick(s, "name"),
                pick(s, "cities_count"), pick(s, "trucks_count"), pick(s, "orders_count")])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log(f"snapshot {snap} stored ({len(payload)} scenarios)")
    return snap


def cycle(args):
    # Open the DB only for the duration of one cycle, so a solver process
    # can open it between cycles (DuckDB allows one writer process at a time).
    with duckdb.connect(str(C.DB_PATH)) as con:
        init_schema(con)
        snap = fetch_snapshot(con, only=args.scenario, force=args.force)
        if snap and not args.no_prepare:
            import prepare
            prepare.run(con)
    if snap and args.on_change:
        log(f"running hook: {args.on_change}")
        rc = subprocess.run(args.on_change, shell=True).returncode
        log(f"hook exited with {rc}")
    return snap


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", action="append", help="scenario id to fetch (repeatable); default all")
    p.add_argument("--force", action="store_true", help="write a snapshot even if unchanged")
    p.add_argument("--no-prepare", action="store_true", help="skip prepare.sql + checks after a new snapshot")
    p.add_argument("--watch", action="store_true", help="keep polling")
    p.add_argument("--every", type=float, default=5, help="minutes between polls in --watch (default 5)")
    p.add_argument("--on-change", help="shell command to run after a new snapshot (e.g. your solver)")
    args = p.parse_args()

    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not args.watch:
        cycle(args)
        return
    log(f"watching {C.BASE_URL} every {args.every} min (Ctrl+C to stop)")
    while True:
        try:
            cycle(args)
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # keep watching even if one cycle fails (incl. failed checks)
            log(f"cycle FAILED: {e}")
        args.force = False
        time.sleep(args.every * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
