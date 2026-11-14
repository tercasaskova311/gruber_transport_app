"""
  1. Design tokens       colours, type scale, radii, sizes, role presets
  2. Loading data        scenarios and plans from the team's DuckDB (data/hackathon.duckdb)
  3. Route calculations  identical to app.py
  4. Components          header, number strip, side panel sections, stop timeline, legend
  5. The map             classic OpenStreetMap basemap, blended routes
  6. The page            role tabs; number strip, map + side panel

Run it from the repo root (the theme is in .streamlit/config.toml there):
    python -m streamlit run dashboard/app.py
"""

import json
import math
from html import escape
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import PolyLineTextPath
from streamlit_folium import st_folium

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import roads                                    # noqa: E402  real road shapes for the map (cached file)


# =============================================================================
# 1. DESIGN TOKENS
#    Two atmospheres of one product. Every colour in the app comes from the active
#    palette, so both themes share exactly the same layout, type and components.
# =============================================================================
BRAND_NAME = "Logi-Wise"
# Base map: OpenStreetMap's own classic tiles (no API key). NOT CARTO: we can't use it.
# OSM's colours are loud, so MAP_TINT calms them in the browser (less colour, a bit lighter),
# and our routes, stops and unserved orders are what you see first. "none" = original look.
MAP_CREDIT = ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · '
              'roads: <a href="https://project-osrm.org">OSRM</a>')
_OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

THEMES = {
    # ---------------- Light ----------------
    "light": dict(
        TEXT="#272B33", MUTED="#5E6575", FAINT="#8C92A1",
        ACCENT="#22A08C", AQUA="#8FE3C8", MAUVE="#D3AFC6", RED="#FF1744",          # neon red: unserved orders
        # truck types: standard = amber, refrigerated = dark blue, hazmat = orange (like ADR plates)
        ROUTE="#E5A500", ROUTE_COLD="#1F3FA8", ROUTE_HAZMAT="#E8590C",
        TRUCK_BG="#1D4ED8", GREEN="#3DDC7A", STOP_HOLLOW="#FFFFFF",   # light green stops ...
        STOP_EDGE="#15803D",                            # ... with a thin dark-green edge, so they show on the pale map
        TRUCK_COLOURS=["#2F8FDB", "#8A63E8", "#13A386", "#EE6A4C", "#C64FA8",
                       "#2AAFC4", "#6B7BDB", "#5E9E3C", "#B7792A", "#4A5468"],
        PAGE_BG="#F2F4F7",
        PANEL="#FFFFFF",
        PANEL_BORDER="rgba(255,255,255,0.70)",
        EDGE="0 0 0 0 transparent",
        LIFT="0 4px 12px rgba(20,16,40,0.10)",
        SHEEN="rgba(255,255,255,0.85)", TRUCK_TINT="16%", RIM_OPACITY="0.8",
        HAIR="rgba(39,43,51,0.08)", HAIR_SHADOW="rgba(255,255,255,0.7)",
        TRACK="rgba(39,43,51,0.09)", HOVER="rgba(255,255,255,0.45)",
        ACTIVE_BG="rgba(143,227,200,0.24)", ACTIVE_RING="rgba(143,227,200,0.65)",
        NODE_RING="rgba(255,255,255,0.9)", NODE_HOLLOW="#FFFFFF", NODE_GLYPH="#FFFFFF",
        INPUT_BG="rgba(255,255,255,0.55)", INPUT_BORDER="rgba(255,255,255,0.9)",
        INPUT_SHADOW="inset 0 1px 0 #FFFFFF, 0 1px 6px rgba(60,66,96,0.08)",
        MENU_BG="#FFFFFF", MENU_HOVER="rgba(143,227,200,0.22)",
        SIDEBAR_BG="#FFFFFF",
        SIDEBAR_BORDER="rgba(255,255,255,0.9)",
        SEG_ON_BG="#FFFFFF",
        SEG_ON_SHADOW="0 0 0 1px #D5DAE1",
        STAGE_RING="rgba(255,255,255,0.75)",
        STAGE_SHADOW="0 2px 4px rgba(60,66,96,0.06), 0 30px 70px rgba(90,84,140,0.20)",
        BTN_PRIMARY="#22A08C", BTN_PRIMARY_TEXT="#FFFFFF",
        BTN_SHADOW="0 6px 16px rgba(34,160,140,0.32)", BTN_SECONDARY_BG="rgba(255,255,255,0.55)",
        ORB_RING="rgba(255,255,255,0.9)", LOGO_GLOW="rgba(120,110,190,0.30)",
        # map
        FLOAT_BG="#FFFFFF",
        MAP_TILES=_OSM_TILES, MAP_BG="#EEF1F2",
        MAP_TINT="saturate(0.3) brightness(1.06) contrast(0.92)",   # OSM, calmed: muted colours
        ROUTE_INK="#6131CF", ROUTE_BLEND="normal", ROUTE_GLOW=False,     # white edge keeps crossings clean
        # load on board 0-20 %, ..., 80-100 %: light -> deep violet (fuller = darker).
        # Violet: the one hue not used by the OSM map (blue water, green land, orange roads),
        # the stops (green), unserved orders (red) or the trucks (near-black).
        LOAD_RAMP=["#B39DFB", "#916CF3", "#7043E3", "#5320BF", "#3A0E8A"],
        TRUCK_ICON="#232733", TRUCK_ICON_EDGE="#FFFFFF",
        MAP_SHEEN="none",
        MAP_CONTROL_BG="rgba(255,255,255,0.82)", MAP_CONTROL_LINE="rgba(39,43,51,0.08)",
        TOOLTIP_BG="#FFFFFF",
        CITY_FILL="#5E6680", CITY_RING="#FFFFFF", LABEL_TEXT="#2E333D", LABEL_HALO="#FFFFFF",
        CASING="#FFFFFF", CASING_OPACITY=0.95, GLOW_SELECTED=0.24, GLOW=0.17, FADED=0.10,
        PILL_TEXT="#FFFFFF", MARKER_RING="rgba(255,255,255,0.9)",
    ),
    # ---------------- Dark ----------------
    "dark": dict(
        TEXT="#F2EEF8", MUTED="#B9B0D0", FAINT="#8E85A8",
        ACCENT="#5FD6BE", AQUA="#8FE3C8", MAUVE="#C99BC0", RED="#FF2E63",          # neon red: unserved orders
        ROUTE="#FFD23F", ROUTE_COLD="#5B8CFF", ROUTE_HAZMAT="#FF8A4C",
        TRUCK_BG="#3B82F6", GREEN="#6EF59A", STOP_HOLLOW="#1B1530",
        STOP_EDGE="#0E2A1A",
        TRUCK_COLOURS=["#5CB4F5", "#A98BFF", "#3FD3AE", "#FF8C6E", "#E77CCB",
                       "#4FD3E3", "#909DFF", "#8FD16E", "#E6A957", "#B4BDD3"],
        PAGE_BG="#1B1630",
        PANEL="#231C38",
        PANEL_BORDER="rgba(255,255,255,0.12)",
        EDGE="0 0 0 0 transparent",
        LIFT="0 4px 12px rgba(0,0,0,0.35)",
        SHEEN="rgba(255,255,255,0.13)", TRUCK_TINT="24%", RIM_OPACITY="0.55",
        HAIR="rgba(255,255,255,0.09)", HAIR_SHADOW="rgba(0,0,0,0.25)",
        TRACK="rgba(255,255,255,0.12)", HOVER="rgba(255,255,255,0.06)",
        ACTIVE_BG="rgba(95,214,190,0.16)", ACTIVE_RING="rgba(95,214,190,0.50)",
        NODE_RING="rgba(33,27,53,0.95)", NODE_HOLLOW="#2A2240", NODE_GLYPH="#16122A",
        INPUT_BG="rgba(255,255,255,0.07)", INPUT_BORDER="rgba(255,255,255,0.14)",
        INPUT_SHADOW="inset 0 1px 0 rgba(255,255,255,0.08), 0 1px 6px rgba(0,0,0,0.25)",
        MENU_BG="#2C2442", MENU_HOVER="rgba(95,214,190,0.16)",
        SIDEBAR_BG="#211B35",
        SIDEBAR_BORDER="rgba(255,255,255,0.08)",
        SEG_ON_BG="rgba(255,255,255,0.14)",
        SEG_ON_SHADOW="0 0 0 1px rgba(255,255,255,0.2)",
        STAGE_RING="rgba(255,255,255,0.10)",
        STAGE_SHADOW="0 2px 4px rgba(0,0,0,0.25), 0 30px 70px rgba(8,4,24,0.55)",
        BTN_PRIMARY="#43BFA6", BTN_PRIMARY_TEXT="#16122A",
        BTN_SHADOW="0 6px 18px rgba(95,214,190,0.28)", BTN_SECONDARY_BG="rgba(255,255,255,0.08)",
        ORB_RING="rgba(255,255,255,0.35)", LOGO_GLOW="rgba(150,118,232,0.45)",
        # map
        FLOAT_BG="#231C38",
        MAP_TILES=_OSM_TILES, MAP_BG="#1E1830",
        MAP_TINT="saturate(0.35) brightness(0.62) contrast(1.05)",   # OSM, muted and dimmed for dark mode
        ROUTE_INK="#9068F5", ROUTE_BLEND="screen", ROUTE_GLOW=True,      # on the dark map, overlapping routes add up and get brighter
        # load on board 0-20 %, ..., 80-100 %: deep violet -> bright lilac (fuller = brighter on the dark map)
        LOAD_RAMP=["#4A2A99", "#6A40D8", "#8E66F5", "#B99CFF", "#ECE4FF"],
        TRUCK_ICON="#F4F1FA", TRUCK_ICON_EDGE="#14111F",
        MAP_SHEEN="none",
        MAP_CONTROL_BG="rgba(52,43,74,0.88)", MAP_CONTROL_LINE="rgba(255,255,255,0.10)",
        TOOLTIP_BG="#2C2442",
        CITY_FILL="#CFC6EC", CITY_RING="#211B35", LABEL_TEXT="#EDE8F7", LABEL_HALO="#1B1530",
        CASING="#1B1530", CASING_OPACITY=0.85, GLOW_SELECTED=0.34, GLOW=0.24, FADED=0.16,
        PILL_TEXT="#16122A", MARKER_RING="rgba(27,21,48,0.9)",
    ),
}
THEME_NAMES = {"light": "light mode", "dark": "dark mode"}


def apply_theme(name):
    """Make the chosen palette the active one. Every component reads these names when it is drawn."""
    globals().update(THEMES[name])


apply_theme("light")                                  # light is the default


# Layout: the map fills the screen; the side panel runs down the right edge with the view menu on top;
# the map gets small floating controls: brand + refresh + theme top-left, zoom top-right,
# scale + credit bottom-left; the legend is the footer of the side panel.
DOCK_WIDTH = 400           # the side panel along the right edge
TABS_H = 56                # height of the role tabs at the top of the side panel
INSET = 16                 # floating controls sit this far from the edges of the map area
R_PANEL = 22               # corner radius: panels (number strip, side panel, map)
R_INNER = 14               # corner radius: anything inside a panel (inputs, rows, buttons)

# What each role sees. Each role gets its own screen, not the same screen with a different label.
ROLE_PRESETS = {
    "Dispatcher": ["Map", "Fleet table", "Truck details", "Stops", "Orders not in plan"],
    "Driver":     ["Map", "Truck details", "Stops"],                                           # one truck only
}
# The views in the ☰ menu at the top of the side panel: icon and one line of what you get.
ROLE_INFO = {
    "Dispatcher": (":material/hub:", "The whole fleet: every route and unserved order"),
    "Driver":     (":material/local_shipping:", "One truck, stop by stop"),
}


# =============================================================================
# 2. LOADING DATA
#    SWAP POINT: when the team's DuckDB tables are ready, only the functions
#    in this section change. Everything below them stays the same.
#
#    Today: each folder inside data/ is one scenario, containing files in the
#    official API formats: cities.json, trucks.json, orders.json,
#    distance_matrix.json, plus one or more plan files named plan*.json.
# =============================================================================
HERE = Path(__file__).resolve().parent
# The team's DuckDB (built by ingestion/run_all.sh, plans added by solver/run.py).
# Scenarios come from raw.cur_* (the API JSON as fetched), plans from results.runs.
DB_PATH = HERE.parent / "data" / "hackathon.duckdb"
MAX_RUNS = 40                                 # plans listed per scenario, best score first
SCENARIO = "scenario_competitive"             # the one scenario we plan for from now on


def _db():
    import duckdb
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(ttl=30)                        # re-read every 30 s, so new solver runs show up
def list_scenarios():
    """Every scenario that has at least one scored plan in results.runs."""
    if not DB_PATH.exists():
        return []
    with _db() as con:
        return [r[0] for r in con.execute("SELECT DISTINCT scenario_id FROM results.runs ORDER BY 1").fetchall()]


@st.cache_data(ttl=30) # re-read every 30 s, so new solver runs show up
def _runs(scenario):
    with _db() as con:
        return con.execute("""
            SELECT run_id, algo, source, score, orders_fulfilled, orders_total, n_violations,
                   strftime(created_at, '%d %b %H:%M'), params_json->>'experiment'
            FROM results.runs WHERE scenario_id = ?
            ORDER BY n_violations = 0 DESC, score DESC LIMIT ?""", [scenario, MAX_RUNS]).fetchall()


def _run_label(r):
    run_id, algo, source, score, done, total, viol, when, exp = r
    tags = " · ".join(x for x in (algo, exp, "API" if source in ("score", "simulate") else None) if x)
    warn = f" · {viol} violations" if viol else ""
    return f"{score:.2f} · {done}/{total} orders · {tags} · {when}{warn} · {run_id}"


def _run_id(plan_label):
    return plan_label.rsplit(" · ", 1)[-1]


def list_plans(scenario):
    return [_run_label(r) for r in _runs(scenario)]


@st.cache_data(ttl=300)
def load_scenario(scenario):
    with _db() as con:
        def objs(table):
            return [json.loads(r[0]) for r in con.execute(
                f"SELECT raw_json FROM raw.cur_{table} WHERE scenario_id = ? ORDER BY id", [scenario]).fetchall()]
        dist = {}
        for a, b, km in con.execute("SELECT from_city, to_city, km FROM raw.cur_distances "
                                    "WHERE scenario_id = ?", [scenario]).fetchall():
            dist.setdefault(a, {})[b] = int(km) if km == int(km) else km
        cities, trucks, orders = objs("cities"), objs("trucks"), objs("orders")
    if not cities:
        raise FileNotFoundError(f"{scenario} has no data in {DB_PATH.name}; run ingestion/run_all.sh")
    return {
        "cities": {c["id"]: c for c in cities},
        "trucks": {t["id"]: t for t in trucks},
        "orders": {o["id"]: o for o in orders},
        "distances": dist,
    }


@st.cache_data(ttl=300)
def load_plan(scenario, plan_file):
    with _db() as con:
        return json.loads(con.execute("SELECT plan_json FROM results.runs WHERE run_id = ?",
                                      [_run_id(plan_file)]).fetchone()[0])


@st.cache_data(ttl=600, show_spinner="Checking every unserved order against the exact score…")
def explain_unserved(scenario, plan_file):
    """Why each unserved order is unserved + what one extra truck would do (solver/explain.py).
    Uses the solver's exact evaluator; about half a second, cached per plan."""
    solver_dir = str(HERE.parent / "solver")
    if solver_dir not in sys.path:
        sys.path.insert(0, solver_dir)                # solver modules import each other flat
    import explain                                    # noqa: PLC0415
    from instance import load_from_db                 # noqa: PLC0415
    return explain.explain_plan(load_from_db(scenario), load_plan(scenario, plan_file))


@st.cache_data(ttl=30)
def baseline_score(scenario):
    """Best score of the plain greedy start (algo 'construct'), or None if it was never run."""
    with _db() as con:
        r = con.execute("SELECT max(score) FROM results.runs WHERE scenario_id = ? AND algo = 'construct' "
                        "AND n_violations = 0", [scenario]).fetchone()
    return r[0] if r else None


def load_official(scenario, plan_file):
    """The exact score of a plan (verified simulator, or the API for source=score)."""
    with _db() as con:
        r = con.execute("""SELECT score, source, orders_fulfilled, orders_total, orders_late, n_violations,
                                  fulfillment, cost_efficiency, loaded_ratio, co2_efficiency
                           FROM results.runs WHERE run_id = ?""", [_run_id(plan_file)]).fetchone()
    keys = ("score", "source", "fulfilled", "total", "late", "violations", "F", "C", "L", "E")
    return dict(zip(keys, r))


# =============================================================================
# 3. ROUTE CALCULATIONS
#    A plan is just a list of stops per truck. Walking through the stops while
#    keeping a running load (+weight at pickup, -weight at delivery) tells us
#    which legs are driven loaded or empty, and the km, cost and CO2.
#    This is NOT the simulator: no time windows, breaks or official score.
# =============================================================================
def km_between(data, city_a, city_b):
    if city_a == city_b:
        return 0                       # consecutive stops in the same city cost 0 km
    return data["distances"][city_a][city_b]


def analyse_plan(data, plan):
    trucks_out = {}
    problems = []
    completed = set()                  # orders picked up AND delivered correctly
    taken_by = {}                      # order id -> truck that carries it

    for truck_id, stops in plan.items():
        truck = data["trucks"].get(truck_id)
        if truck is None:
            problems.append(f"The plan mentions truck {truck_id}, which is not in this scenario.")
            continue

        position = truck["start_city"]
        on_board = {}                  # order id -> weight currently in the truck
        load = 0
        legs, stop_rows, stop_cities = [], [], []

        for number, stop in enumerate(stops, start=1):
            action, order_id = stop.get("action"), stop.get("order")
            order = data["orders"].get(order_id)
            if order is None:
                problems.append(f"{truck_id}, stop {number}: order {order_id} does not exist.")
                continue
            if action not in ("pickup", "delivery"):
                problems.append(f"{truck_id}, stop {number}: unknown action '{action}'.")
                continue
            if taken_by.get(order_id, truck_id) != truck_id:
                problems.append(f"{order_id} appears on {taken_by[order_id]} and {truck_id}.")
                continue
            if action == "delivery" and order_id not in on_board:
                problems.append(f"{truck_id}, stop {number}: delivery of {order_id} before its pickup.")
                continue
            if action == "pickup" and order_id in on_board:
                problems.append(f"{truck_id}, stop {number}: {order_id} is picked up twice.")
                continue

            taken_by[order_id] = truck_id
            city = order["pickup_city"] if action == "pickup" else order["delivery_city"]
            km = km_between(data, position, city)
            if km > 0:
                legs.append({"from": position, "to": city, "km": km, "load_kg": load,
                             "stop": len(stop_rows) + 1})     # this leg ends at stop number N
            position = city

            if action == "pickup":
                on_board[order_id] = order["weight_kg"]
                load += order["weight_kg"]
                if load > truck["capacity_kg"]:
                    problems.append(f"{truck_id}, stop {number}: load {load:,} kg is above capacity "
                                    f"{truck['capacity_kg']:,} kg (the official simulator rejects this pickup).")
                needed = order.get("required_truck_type")
                if needed and needed != truck["type"]:
                    problems.append(f"{truck_id}: {order_id} needs a {needed} truck, this one is {truck['type']}.")
            else:
                load -= on_board.pop(order_id)
                needed = order.get("required_truck_type")
                if not needed or needed == truck["type"]:
                    completed.add(order_id)

            stop_cities.append(city)
            stop_rows.append({
                "Action": "▲ Pickup" if action == "pickup" else "▼ Delivery",
                "Order": order_id,
                "City": data["cities"][city]["name"],
                "km": km,
                "Load (kg)": load,
            })

        for order_id in on_board:
            problems.append(f"{truck_id}: {order_id} is picked up but never delivered.")

        total_km = sum(leg["km"] for leg in legs)
        trucks_out[truck_id] = {
            "legs": legs,
            "stops": stop_rows,
            "stop_cities": stop_cities,
            "orders": len({row["Order"] for row in stop_rows}),
            "km": total_km,
            "loaded_km": sum(leg["km"] for leg in legs if leg["load_kg"] > 0),
            "cost": total_km * truck["cost_per_km"],
            "co2": total_km * truck["co2_per_km"],
            "peak_kg": max((row["Load (kg)"] for row in stop_rows), default=0),
        }

    not_in_plan = [o for oid, o in data["orders"].items() if oid not in completed]
    return trucks_out, not_in_plan, problems


# =============================================================================
# 4. COMPONENTS
#    One type scale, two corner radii, one inset. Every component is HTML + CSS
#    fed by the unchanged calculations above.
# =============================================================================
def inject_css():
    st.markdown(f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Instrument+Serif&display=swap');

      /* ---------- Page ---------- */
      [data-testid="stApp"] {{ background: {PAGE_BG}; background-attachment: fixed; color: {TEXT}; }}
      /* Streamlit's own top bar would lie over our header; the app has no sidebar or menu to open */
      [data-testid="stHeader"], [data-testid="stDecoration"], [data-testid="stMainMenu"] {{ display: none; }}
      [data-testid="stExpandSidebarButton"], [data-testid="stExpandSidebarButton"] *,
      [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapseButton"] * {{ color: {TEXT} !important; }}   /* developer menu: not needed here, and it crowded the theme toggle */
      .block-container, [data-testid="stMainBlockContainer"] {{ padding: {TABS_H + 28}px 22px 14px !important; max-width: none; }}
      /* Top-left of the map: brand, refresh, theme as small floating pills */
      .st-key-topbar {{ position: fixed !important; top: {INSET}px; left: {INSET}px; z-index: 7;
                        max-width: calc(100vw - {DOCK_WIDTH + 2 * INSET + 110}px); }}
      .st-key-topbar [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
      .pill {{ background: {FLOAT_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 999px;
               box-shadow: {EDGE}, 0 4px 14px rgba(20,16,40,0.16); }}
      /* View menu: the top strip of the side panel */
      .st-key-rolebar {{ position: fixed !important; top: 0; right: 0; width: {DOCK_WIDTH}px; height: {TABS_H}px;
                         z-index: 7; gap: 0 !important; background: {FLOAT_BG};
                         border-left: 1px solid {PANEL_BORDER}; border-bottom: 1px solid {HAIR}; }}
      .st-key-rolebar {{ padding: 0 18px !important; gap: 12px !important; }}
      .st-key-role_menu button {{ width: 40px; height: 40px; min-height: 0; padding: 0; border-radius: 12px !important;
                                  background: {BTN_SECONDARY_BG}; border: 1px solid {INPUT_BORDER}; }}
      .st-key-role_menu button:hover {{ background: {HOVER} !important; }}
      .st-key-role_menu button span {{ font-size: 1.35rem; color: {TEXT} !important; }}
      .st-key-role_menu [data-testid="stPopoverButton"] > div > :nth-child(2) {{ display: none !important; }}  /* no ^ arrow */
      .role-now .k {{ font-size: 0.66rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: {FAINT}; }}
      .role-now .v {{ font-size: 1.05rem; font-weight: 700; color: {TEXT}; line-height: 1.2; }}
      /* The menu that opens: a plain list, icon + name, the current view tinted and ticked */
      .st-key-role_options {{ gap: 2px !important; min-width: 190px; }}
      .st-key-role_options button {{ justify-content: flex-start !important; width: 100%; padding: 8px 12px !important;
                                     min-height: 0; border-radius: 10px !important; color: {TEXT} !important; }}
      .st-key-role_options button:hover {{ background: {HOVER} !important; }}
      .st-key-role_options button p {{ font-size: 0.95rem !important; font-weight: 600; }}
      .st-key-role_options button span {{ color: {MUTED} !important; }}
      [data-testid="stSidebar"] {{ background: {SIDEBAR_BG} !important; backdrop-filter: blur(24px) saturate(160%);
                                   border-right: 1px solid {SIDEBAR_BORDER}; }}
      [data-testid="stSidebar"] button, [data-testid="stSidebarCollapseButton"] * {{ color: {TEXT}; }}
      [data-testid="stSidebar"] hr {{ border-color: {HAIR}; }}

      /* Streamlit's own text follows the active palette too */
      [data-testid="stWidgetLabel"] p {{ color: {TEXT} !important; }}
      [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {MUTED} !important; }}
      [data-testid="stExpander"] summary, [data-testid="stExpander"] summary p,
      [data-testid="stExpander"] summary span {{ color: {TEXT} !important; }}
      [data-testid="stExpanderDetails"] p, [data-testid="stExpanderDetails"] li {{ color: {TEXT}; }}
      [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color: {TEXT}; }}

      /* ---------- Type scale (Manrope everywhere; the serif is only the brand) ---------- */
      .ov   {{ font-size: 0.66rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
               color: {MUTED}; line-height: 1.2; white-space: nowrap; }}
      .h2   {{ font-size: 1.05rem; font-weight: 700; letter-spacing: -0.01em; line-height: 1.25; color: {TEXT}; }}
      .h3   {{ font-size: 1.3rem; font-weight: 700; letter-spacing: -0.015em; line-height: 1.15; color: {TEXT}; }}
      .vl   {{ font-size: 1.32rem; font-weight: 700; letter-spacing: -0.015em; line-height: 1.2; color: {TEXT};
               font-variant-numeric: tabular-nums; white-space: nowrap; }}
      .vm   {{ font-size: 1.02rem; font-weight: 700; letter-spacing: -0.01em; line-height: 1.3; color: {TEXT};
               font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .body {{ font-size: 0.86rem; font-weight: 500; line-height: 1.35; color: {TEXT}; white-space: nowrap; }}
      .strong {{ font-weight: 700; }}
      .cap  {{ font-size: 0.74rem; font-weight: 500; line-height: 1.3; color: {MUTED}; white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }}
      .unit {{ font-size: 0.68em; font-weight: 600; color: {MUTED}; margin-left: 3px; letter-spacing: 0; }}
      .muted {{ color: {MUTED}; font-weight: 500; }}

      /* ---------- Panels: solid, hairline border, one soft shadow ---------- */
      .lg, .st-key-dock, .st-key-dock_static, .st-key-picker, .st-key-role [role="radiogroup"],
      .st-key-theme_toggle button {{
          position: relative; isolation: isolate; background: {PANEL};
          border: 1px solid {HAIR}; box-shadow: 0 2px 10px rgba(20,16,40,0.10);
      }}
      .hair {{ height: 1px; background: {HAIR}; box-shadow: 0 1px 0 {HAIR_SHADOW}; }}

      /* ---------- Header ---------- */
      .brand {{ display: flex; align-items: center; gap: 10px; min-width: 0; padding: 6px 18px 6px 7px; }}
      .brand-title {{ font-size: 1.3rem; font-weight: 800; letter-spacing: -0.03em; line-height: 1; color: {TEXT};
                      white-space: nowrap; }}
      .brand-title span {{ color: {ROUTE_INK}; }}
      .brand .mark {{ flex: none; display: block; }}
      .brand .ov {{ margin-top: 4px; letter-spacing: 0.14em; font-size: 0.6rem; }}
      .chips {{ display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }}
      .chip {{ display: inline-flex; align-items: center; gap: 8px; padding: 7px 14px; border-radius: 999px;
               font-size: 0.78rem; font-weight: 600; color: {TEXT}; white-space: nowrap; }}
      .chip .dot {{ width: 8px; height: 8px; border-radius: 50%; flex: none; }}

      /* Segmented switches */
      .st-key-role [data-testid="stButtonGroup"], .st-key-dock_tab [data-testid="stButtonGroup"] {{ display: flex; justify-content: flex-end; }}
      .st-key-role [role="radiogroup"], .st-key-dock_tab [role="radiogroup"] {{ display: inline-flex; flex-wrap: nowrap; gap: 2px; padding: 4px;
                                          border-radius: 999px; }}
      .st-key-role button, .st-key-dock_tab button {{ border: none !important; background: transparent !important; box-shadow: none !important;
                             border-radius: 999px !important; padding: 6px 16px !important; min-height: 0 !important;
                             color: {MUTED} !important; font-weight: 600; transition: background .2s ease, box-shadow .2s ease; }}
      .st-key-role button p, .st-key-dock_tab button p {{ font-size: 0.84rem !important; color: inherit !important; }}
      .st-key-role button[aria-checked="true"], .st-key-dock_tab button[aria-checked="true"] {{ color: {TEXT} !important; background: {SEG_ON_BG} !important;
                                                  box-shadow: {SEG_ON_SHADOW} !important; }}

      .st-key-dock_tab [data-testid="stButtonGroup"] {{ justify-content: flex-start; }}
      /* list tabs: plain underline tabs, like a normal website */
      .st-key-dock_tab [role="radiogroup"] {{ background: transparent !important; box-shadow: none !important; padding: 0 !important;
            border-radius: 0 !important; gap: 18px !important; border-bottom: 1px solid {HAIR}; width: 100%; }}
      .st-key-dock_tab button {{ border-radius: 0 !important; padding: 8px 2px !important; }}
      .st-key-dock_tab button[aria-checked="true"] {{ background: transparent !important;
            box-shadow: inset 0 -2px 0 {ACCENT} !important; color: {TEXT} !important; }}

      /* Theme toggle: one round button with a sun or moon */
      .st-key-theme_toggle {{ display: flex; justify-content: flex-end; }}
      .st-key-theme_toggle button {{ width: 36px; height: 36px; min-height: 0; padding: 0; border-radius: 50% !important;
                                     color: {TEXT} !important; transition: transform .15s ease; }}
      .st-key-theme_toggle button:hover {{ transform: scale(1.05); }}
      .st-key-theme_toggle button:active {{ transform: scale(0.96); }}
      .st-key-theme_toggle button span {{ font-size: 1.2rem; color: {TEXT} !important; }}

      /* ---------- Stage: the map is the whole background; header, side panel and legend float on it ---------- */
      .st-key-mapbox {{ position: fixed !important; inset: 0; z-index: 0; gap: 0 !important; }}
      .st-key-mapbox iframe, iframe[title="streamlit_folium.st_folium"] {{
          position: fixed; inset: 0; width: 100vw !important; height: 100vh !important; display: block; border: 0; }}
      /* Legend: the footer of the side panel */
      .st-key-legend_slot {{ flex: none; padding: 6px 0 10px; border-top: 1px solid {HAIR}; gap: 12px !important; }}
      .st-key-legend_slot details {{ border: none !important; background: transparent !important; }}
      .st-key-legend_slot summary {{ padding: 8px 2px !important; }}
      .st-key-legend_slot summary p {{ font-size: 0.72rem !important; font-weight: 700; letter-spacing: 0.12em;
                                       text-transform: uppercase; color: {FAINT} !important; }}
      .st-key-legend_slot [data-testid="stExpanderDetails"] {{ padding: 2px 2px 6px !important; gap: 14px; }}
      .st-key-ribbon_slot, .st-key-ribbon_static {{ margin-bottom: 4px; }}
      /* Panels over the map are solid, so the map never shows through */
      .st-key-dock {{ background: {FLOAT_BG} !important; }}

      /* ---------- Number strip: label / value / caption on three shared lines ---------- */
      .ribbon {{ width: 100%; display: flex; flex-wrap: wrap; row-gap: 12px; padding: 14px 6px;
                 border-radius: {R_PANEL}px; }}
      .ribbon .cell {{ flex: 1 1 140px; padding: 0 16px; display: flex; flex-direction: column; gap: 3px; min-width: 0; }}
      .ribbon .cell + .cell {{ border-left: 1px solid {HAIR}; box-shadow: -1px 0 0 {HAIR_SHADOW}; }}
      .ribbon .vl, .ribbon .score {{ height: 1.75rem; display: flex; align-items: flex-end; }}
      .ribbon .score {{ font-size: 1.55rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.1;
                        color: {TEXT}; }}

      /* ---------- Side panel: one surface, sections divided by space and thin lines ---------- */
      .st-key-dock {{ position: fixed !important; top: {TABS_H}px; right: 0; bottom: 0;
                      width: {DOCK_WIDTH}px; z-index: 6; border-radius: 0; border: none !important;
                      border-left: 1px solid {PANEL_BORDER} !important; box-shadow: -2px 0 14px rgba(20,16,40,0.10) !important;
                      padding: 18px 18px 6px; gap: 12px; overflow: hidden; }}
      .st-key-picker {{ border-radius: {R_PANEL}px; padding: 16px 18px; gap: 10px; }}
      .st-key-dock_static {{ max-width: 760px; margin: 0 auto; border-radius: {R_PANEL}px; padding: 18px; gap: 12px; }}
      .st-key-dock > div:has(.st-key-dock_scroll) {{ flex: 1 1 auto; min-height: 0; }}
      /* The scroll area reaches past the content edge on each side, so marker rings and glows
         have room and are never clipped; a soft fade at the bottom signals more content. */
      .st-key-dock_scroll {{ height: 100%; overflow-y: auto; overflow-x: hidden; margin: 0 -10px; padding: 2px 10px 22px;
                             gap: 14px; -webkit-mask-image: linear-gradient(#000 calc(100% - 22px), transparent);
                             mask-image: linear-gradient(#000 calc(100% - 22px), transparent); }}
      .st-key-dock_static .st-key-dock_scroll {{ height: auto; overflow: visible; -webkit-mask-image: none; mask-image: none; }}
      .st-key-dock_scroll::-webkit-scrollbar {{ width: 6px; }}
      .st-key-dock_scroll::-webkit-scrollbar-thumb {{ background: {TRACK}; border-radius: 999px; }}
      .st-key-dock [data-testid="stMarkdownContainer"], .st-key-dock_static [data-testid="stMarkdownContainer"],
      .st-key-picker [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
      .dock-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }}

      /* Inputs and their menus */
      [data-testid="stSelectbox"] [role="group"] {{ background: {INPUT_BG} !important; border-radius: {R_INNER}px !important;
            border: 1px solid {INPUT_BORDER} !important; box-shadow: {INPUT_SHADOW}; }}
      [data-testid="stSelectbox"] [role="group"]:focus-within {{ box-shadow: 0 0 0 3px {ACTIVE_RING}; }}
      [data-testid="stSelectbox"] input[role="combobox"] {{ font-size: 0.86rem; font-weight: 600; color: {TEXT} !important;
                                                            -webkit-text-fill-color: {TEXT}; }}
      [data-testid="stSelectbox"] button, [data-testid="stSelectbox"] svg {{ color: {MUTED} !important; }}
      [data-testid="stSelectboxVirtualDropdown"] {{ background: {MENU_BG} !important; border: 1px solid {INPUT_BORDER};
                                                    border-radius: {R_INNER}px; box-shadow: {LIFT}; }}
      [data-testid="stSelectboxVirtualDropdown"] [role="option"] {{ color: {TEXT} !important; font-size: 0.86rem; }}
      [data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover,
      [data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] {{ background: {MENU_HOVER} !important; }}
      [data-testid="stExpander"] details {{ background: {INPUT_BG}; border: 1px solid {INPUT_BORDER}; border-radius: {R_INNER}px; }}
      .st-key-panels button {{ border-radius: 999px; background: {INPUT_BG}; border-color: {INPUT_BORDER}; color: {TEXT}; }}
      .st-key-panels button[aria-checked="true"], .st-key-panels button[aria-pressed="true"] {{
          background: {ACTIVE_BG}; border-color: {ACTIVE_RING}; }}
      .st-key-panels button p {{ color: {TEXT} !important; }}

      .ticon {{ display: flex; align-items: center; justify-content: center; width: 24px; flex: none; }}
      .ticon.big {{ width: 36px; }}
      .section-head {{ display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 4px; }}

      /* Fleet list: rows, not cards */
      .list {{ display: flex; flex-direction: column; gap: 2px; }}
      .list-head {{ display: flex; justify-content: space-between; padding: 0 12px 4px 48px; }}
      .list-head .ov {{ font-size: 0.6rem; }}
      .row {{ display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; gap: 12px;
              padding: 9px 10px; border-radius: {R_INNER}px; transition: background .2s ease; }}
      .row:hover {{ background: {HOVER}; }}
      .row.active {{ background: {ACTIVE_BG}; box-shadow: inset 0 0 0 1px {ACTIVE_RING}; }}
      .row .main {{ min-width: 0; }}
      .row .side {{ text-align: right; }}
      .meter {{ display: inline-block; vertical-align: middle; width: 56px; height: 5px; border-radius: 999px;
                background: {TRACK}; overflow: hidden; }}
      .meter > i {{ display: block; height: 100%; border-radius: inherit; background: {LOAD_RAMP[3]}; }}
      .meter.over > i {{ background: {RED}; }}
      .metric-line {{ display: flex; align-items: center; justify-content: flex-end; gap: 8px; }}

      /* Truck identity + numbers */
      .identity {{ display: flex; align-items: center; gap: 12px; }}
      .identity > div {{ min-width: 0; }}
      .grid3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); row-gap: 14px; }}
      .grid3 > div {{ padding-left: 12px; border-left: 1px solid {HAIR}; min-width: 0; }}
      .grid3 > div:nth-child(3n+1) {{ padding-left: 0; border-left: none; }}
      .grid3 .vm {{ margin-top: 3px; }}
      .score-text {{ color: {ACCENT}; font-size: 1.2rem; }}

      /* Stop timeline: the line runs exactly through the marker centres (marker 22px, centre at 19px) */
      .timeline {{ position: relative; }}
      .stop {{ position: relative; display: grid; grid-template-columns: 22px minmax(0, 1fr); column-gap: 12px;
               padding: 8px 8px 8px 6px; border-radius: {R_INNER}px; }}
      .stop::before {{ content: ""; position: absolute; left: 16px; width: 2px; top: 0; bottom: 0;
                       background: color-mix(in srgb, var(--c) 40%, transparent); }}
      .stop:first-child::before {{ top: 19px; }}
      .stop:last-child::before {{ bottom: auto; height: 19px; }}
      .stop:only-child::before {{ display: none; }}
      .node {{ position: relative; z-index: 1; width: 22px; height: 22px; border-radius: 50%; display: grid;
               place-items: center; font-size: 9px; line-height: 1; }}
      .stop.pick .node {{ background: var(--c); color: {NODE_GLYPH}; box-shadow: 0 0 0 3px {NODE_RING}; }}
      .stop.drop .node {{ background: {NODE_HOLLOW}; color: var(--c); box-shadow: inset 0 0 0 2px var(--c), 0 0 0 3px {NODE_RING}; }}
      .stop .l1, .stop .l2 {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; }}
      .stop .l2 {{ margin-top: 2px; }}
      .stop .l1 > :first-child, .stop .l2 > :first-child {{ overflow: hidden; text-overflow: ellipsis; }}
      .stop .load {{ display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex: none; }}
      .stop .load .cap {{ width: 46px; text-align: right; }}
      .stop.done .node, .stop.done .l1, .stop.done .l2 {{ opacity: 0.45; }}
      .stop.current {{ background: {ACTIVE_BG}; box-shadow: inset 0 0 0 1px {ACTIVE_RING}; }}
      .stop.current .node {{ box-shadow: 0 0 0 3px {NODE_RING}, 0 0 0 5px {ACTIVE_RING}; }}

      /* Driver progress */
      .progress {{ height: 4px; border-radius: 999px; background: {TRACK}; overflow: hidden; }}
      .progress > i {{ display: block; height: 100%; border-radius: inherit; background: {ACCENT}; }}
      .st-key-dock_scroll [data-testid="stBaseButton-primary"] {{
          background: {BTN_PRIMARY}; border: none; border-radius: {R_INNER}px;
          box-shadow: inset 0 1px 0 rgba(255,255,255,0.40), {BTN_SHADOW}; }}
      .st-key-dock_scroll [data-testid="stBaseButton-primary"] p {{ color: {BTN_PRIMARY_TEXT} !important; }}
      .st-key-dock_scroll [data-testid="stBaseButton-secondary"] {{
          background: {BTN_SECONDARY_BG}; border: 1px solid {INPUT_BORDER}; border-radius: {R_INNER}px;
          box-shadow: {INPUT_SHADOW}; }}
      .st-key-dock_scroll [data-testid="stBaseButton-secondary"] p {{ color: {TEXT} !important; }}
      .st-key-dock_scroll button p {{ font-size: 0.84rem; font-weight: 700; }}

      /* ---------- Legend ---------- */
      .legend {{ display: flex; flex-direction: column; gap: 16px; }}
      .legend .k {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: {FAINT}; }}
      .legend .scale svg {{ display: block; width: 100%; height: 30px; margin-top: 8px; }}
      .legend .ticks {{ display: flex; justify-content: space-between; font-size: 0.78rem; font-weight: 600;
                        color: {MUTED}; margin-top: 4px; }}
      .legend .types {{ display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }}
      .legend .type-row {{ display: flex; align-items: center; gap: 12px; font-size: 0.92rem; color: {TEXT}; }}
      .legend .type-row b {{ font-weight: 700; }}
      .legend .type-row .n {{ margin-left: auto; color: {MUTED}; font-size: 0.82rem; }}
      .legend .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px 14px; }}
      .legend .grid span {{ font-size: 0.92rem; font-weight: 600; color: {TEXT}; gap: 10px; }}
      .st-key-route_colour [data-testid="stButtonGroup"] {{ justify-content: flex-start; }}
      .st-key-route_colour button {{ padding: 6px 16px !important; min-height: 0 !important; }}
      .st-key-route_colour button p {{ font-size: 0.88rem !important; font-weight: 600; }}
      .st-key-route_colour [data-testid="stWidgetLabel"] p {{ font-size: 0.72rem !important; font-weight: 700;
            letter-spacing: 0.12em; text-transform: uppercase; color: {FAINT} !important; }}
      .idle {{ padding: 9px 10px; }}
      .unserved .row {{ grid-template-columns: minmax(0, 1fr) auto; }}
      .unserved .tags {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; max-width: 150px; }}
      .unserved .tag {{ font-size: 0.68rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; white-space: nowrap;
                        color: {RED}; background: color-mix(in srgb, {RED} 10%, transparent); }}
      .legend span {{ display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; font-size: 0.74rem;
                      font-weight: 500; color: {MUTED}; }}

      @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
    </style>""", unsafe_allow_html=True)


def html(markup):
    st.markdown(markup, unsafe_allow_html=True)


TRUCK_TYPES = ["standard", "refrigerated", "hazmat"]


def route_colour(truck):
    """Routes coloured by truck type. 22 colours (one per truck) can't be told apart;
    the type is what a dispatcher needs."""
    return {"refrigerated": ROUTE_COLD, "hazmat": ROUTE_HAZMAT}.get(truck["type"], ROUTE)


LOAD_WEIGHT = [1.3, 1.9, 2.5, 3.1, 3.8]           # fleet view: fuller legs are also drawn a bit thicker


def load_colour(load_kg, capacity_kg):
    """Colour of a leg from how full the truck is (5 steps of LOAD_RAMP, light to dark violet).
    Lines are slightly transparent and blended, so busy corridors stand out too."""
    step = min(len(LOAD_RAMP) - 1, int(5 * load_kg / capacity_kg)) if capacity_kg else 0
    return LOAD_RAMP[step]


def truck_colours(data, colour_by="Load"):
    """The panel uses the same colour as the truck's route on the map
    (with the load heatmap a route has many colours, so the panel keeps plain violet)."""
    return {tid: route_colour(truck) if colour_by == "Truck type" else ROUTE_INK
            for tid, truck in data["trucks"].items()}


def truck_svg(size=22, fill=None):
    """A plain truck (side view, cab on the right). Neutral ink by default (charcoal in light mode,
    white in dark mode) so it never competes with the coloured routes; thin contrasting outline."""
    fill = fill or TRUCK_ICON
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" style="overflow:visible">'
            f'<g fill="{fill}" stroke="{TRUCK_ICON_EDGE}" stroke-width="1.4" stroke-linejoin="round" paint-order="stroke">'
            f'<path d="M1.5 5.5h12.5v10.5H1.5z"/><path d="M14 8.5h4.6l3.9 4.1V16H14z"/>'
            f'<circle cx="6" cy="17.6" r="2.3"/><circle cx="18" cy="17.6" r="2.3"/></g>'
            f'<path d="M15.6 10h2.5l2.2 2.4h-4.7z" fill="{TRUCK_ICON_EDGE}" opacity="0.85"/></svg>')


def compact(n):
    """6500 -> 6.5K, 11000 -> 11K, 900 -> 900"""
    return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "K" if n >= 1000 else f"{n:,}"


def meter(value, maximum):
    share = 0 if not maximum else min(100, 100 * value / maximum)
    over = " over" if maximum and value > maximum else ""
    return f'<span class="meter{over}"><i style="width:{share:.0f}%"></i></span>'


def brand_html():
    # The mark is a route: a pickup (green ring) driven to a delivery (white dot), the same
    # symbols as on the map. Plain colours on purpose: no gradients, nothing decorative.
    mark = (f'<svg class="mark" width="34" height="34" viewBox="0 0 34 34">'
            f'<rect width="34" height="34" rx="10" fill="{ROUTE_INK}"/>'
            f'<path d="M9 24 C 9 14, 25 20, 25 10" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round"/>'
            f'<circle cx="9" cy="24" r="3.6" fill="{ROUTE_INK}" stroke="{GREEN}" stroke-width="2.4"/>'
            f'<circle cx="25" cy="10" r="3.6" fill="#FFFFFF"/></svg>')
    html(f'<div class="brand pill">{mark}<div style="min-width:0">'
         f'<div class="brand-title">Logi<span>-Wise</span></div>'
         f'<div class="ov">Truck planning · Gruber Logistics</div></div></div>')


def chips_html(problems, official):
    """A red warning chip, shown ONLY when the plan breaks a rule (each violation costs 20 points).
    A valid plan (the normal case) shows nothing."""
    bad = official["violations"] if official else len(problems)
    if bad:
        html(f'<div class="chips"><span class="chip lg" title="Each violation costs 20 points.">'
             f'<span class="dot" style="background:{RED}"></span>{bad} violation{"s" if bad != 1 else ""}</span></div>')


def ribbon_html(data, analysis, not_in_plan, official=None, baseline=None):
    total_km = sum(t["km"] for t in analysis.values())
    loaded_km = sum(t["loaded_km"] for t in analysis.values())
    empty_km = total_km - loaded_km
    used = sum(1 for t in analysis.values() if t["km"] > 0)
    done = len(data["orders"]) - len(not_in_plan)
    cost = sum(t["cost"] for t in analysis.values())
    co2 = sum(t["co2"] for t in analysis.values())
    loaded_pct = f"{100 * loaded_km / total_km:.0f}% of km with cargo" if total_km else "&nbsp;"
    cell = lambda label, value, caption, tip: (f'<div class="cell" title="{escape(tip)}"><div class="ov">{label}</div>'
                                               f'<div class="vl">{value}</div><div class="cap">{caption}</div></div>')
    if official:
        gain = official["score"] - baseline if baseline is not None else None
        score_cap = (f"+{gain:.1f} vs simple greedy plan" if gain is not None and gain >= 0.05 else "out of 1,000")
        score_cell = (f'<div class="cell" title="Fulfilled {official["F"]:.1f}% · cost {official["C"]:.1f}% · '
                      f'loaded {official["L"]:.1f}% · CO₂ {official["E"]:.1f}%">'
                      f'<div class="ov">Score</div><div class="score">{official["score"]:.1f}</div>'
                      f'<div class="cap">{score_cap}</div></div>')
        missed = official["total"] - official["fulfilled"]
        orders_cell = cell("Orders delivered", f'{official["fulfilled"]}<span class="unit">/ {official["total"]}</span>',
                           f'{official["late"]} late · {missed} unserved', "On time or up to 60 min late")
    else:
        score_cell = ('<div class="cell"><div class="ov">Score</div><div class="score">—</div>'
                      '<div class="cap">not scored yet</div></div>')
        orders_cell = cell("Orders planned", f'{done}<span class="unit">/ {len(data["orders"])}</span>', "&nbsp;",
                           "Orders this plan picks up and delivers")
    html('<div class="ribbon lg">' + score_cell + orders_cell
         + cell("Distance", f'{total_km:,}<span class="unit">km</span>', f"{used} of {len(data['trucks'])} trucks used",
                "Total km driven by all trucks")
         + cell("Empty km", f'{empty_km:,}<span class="unit">km</span>', loaded_pct, "km driven with nothing on board")
         + cell("Cost", f"€{cost:,.0f}", "est. from €/km", "km × each truck's €/km")
         + cell("CO₂", f'{co2 / 1000:,.1f}<span class="unit">t</span>', "est. from CO₂/km", "km × each truck's CO₂/km")
         + "</div>")


def summary_html(data, analysis, official, baseline=None):
    """Dispatcher: the three numbers that matter, at the top of the side panel."""
    total_km = sum(t["km"] for t in analysis.values())
    empty_km = total_km - sum(t["loaded_km"] for t in analysis.values())
    # Kept simple on purpose: a label and one number per box (details are in the tooltips)
    cell = lambda k, v, tip, cls="vm": (f'<div title="{tip}"><div class="ov">{k}</div><div class="{cls}">{v}</div></div>')
    if official:
        gain = official["score"] - baseline if baseline is not None else None
        tip = f"+{gain:.1f} vs greedy start" if gain is not None and gain >= 0.05 else "out of 1,000"
        score = cell("Score", f'{official["score"]:.1f}', tip, "vm score-text")
        orders = cell("Delivered", f'{official["fulfilled"]}<span class="unit">/ {official["total"]}</span>',
                      f'{official["late"]} delivered late')
    else:
        score = cell("Score", "—", "not scored", "vm score-text")
        orders = cell("Planned", f'{len(data["orders"])}', "")
    html('<div class="grid3">' + score + orders
         + cell("Empty km", f'{empty_km:,}<span class="unit">km</span>', f"of {total_km:,} km driven") + "</div>")


def dock_head_html(title, meta):
    html(f'<div class="dock-head"><div class="h2">{escape(title)}</div><div class="cap">{escape(meta)}</div></div>')


def fleet_list_html(data, analysis, colours, role, highlight=None):
    """Busiest trucks first; trucks without orders are folded into one line at the end.
    The dot colour is the truck's route colour on the map."""
    empty = {"orders": 0, "km": 0, "loaded_km": 0, "peak_kg": 0, "cost": 0, "co2": 0}
    stats = {tid: analysis.get(tid, empty) for tid in data["trucks"]}
    busy = sorted((t for t in stats if stats[t]["orders"]), key=lambda t: (-stats[t]["orders"], -stats[t]["km"]))
    idle = sorted(t for t in stats if not stats[t]["orders"])
    rows = ""
    for tid in busy:
        truck, a = data["trucks"][tid], stats[tid]
        if role == "Manager":          # managers care about money and emissions
            main = (f'<div class="body"><span class="strong">{escape(tid)}</span> <span class="muted">· {a["km"]:,} km</span></div>'
                    f'<div class="cap">{a["orders"]} orders · {escape(truck["type"])}</div>')
            side = f'<div class="body strong">€{a["cost"]:,.0f}</div><div class="cap">{a["co2"] / 1000:,.1f} t CO₂</div>'
        else:
            # average fill over the truck's km: Σ(load × km) / (capacity × km). 26-77 % in the
            # competitive plan, so it tells trucks apart (loaded km and peak load are ~100 % for all)
            ton_km = sum(leg["load_kg"] * leg["km"] for leg in a.get("legs", []))
            fill = 100 * ton_km / (truck["capacity_kg"] * a["km"]) if a["km"] else 0
            main = (f'<div class="body" title="{escape(truck["type"])}"><span class="strong">{escape(tid)}</span></div>'
                    f'<div class="cap">{a["orders"]} orders · {a["km"]:,} km</div>')
            side = (f'<div class="metric-line" title="How full the truck is on average over its km">'
                    f'{meter(fill, 100)}'
                    f'<span class="cap" style="width:32px;text-align:right">{fill:.0f}%</span></div>')
        rows += (f'<div class="row{" active" if tid == highlight else ""}">'
                 f'<span class="ticon">{truck_svg(22, colours[tid])}</span><div class="main">{main}</div>'
                 f'<div class="side">{side}</div></div>')
    if idle:
        rows += (f'<div class="idle cap" title="Not needed in this plan">{len(idle)} truck{"s" if len(idle) != 1 else ""} '
                 f'idle: {", ".join(escape(t) for t in idle)}</div>')
    header = ("" if role == "Manager" else
              '<div class="list-head"><span class="ov">Truck</span><span class="ov">Avg. fill</span></div>')
    html(f'<div class="list">{header}{rows}</div>')


def clock(minutes):
    """Minutes from Day 1 06:00 -> 'Day 2 14:30'."""
    t = 360 + int(minutes)
    return f"Day {t // 1440 + 1} {t % 1440 // 60:02d}:{t % 60:02d}"


def not_served_html(data, not_in_plan, why=None):
    """Orders no truck delivers. Kept simple: the route big, the id and weight small, and at most
    one or two tags for what made it hard (truck type, time window). Details are in the tooltip."""
    if not not_in_plan:
        return
    cities = data["cities"]
    rows = ""
    for o in sorted(not_in_plan, key=lambda o: o["id"]):
        tags, details = [], [f"{o['weight_kg']:,} kg", f"value {o.get('value', 1):g}"]
        if o.get("required_truck_type"):
            tags.append(o["required_truck_type"])
            details.append(f"needs a {o['required_truck_type']} truck")
        if o.get("pickup_window"):
            details.append(f"pickup by {clock(o['pickup_window']['to'])}")
        if o.get("delivery_window"):
            details.append(f"deliver {clock(o['delivery_window']['from'])} – {clock(o['delivery_window']['to'])}")
        if o.get("pickup_window") or o.get("delivery_window"):
            tags.append("time window")
        tag_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in tags)
        r = (why or {}).get("orders", {}).get(o["id"])
        if r:
            details.append(r["text"])
        rows += (f'<div class="row" title="{escape(" · ".join(details))}"><div class="main">'
                 f'<div class="body strong">{escape(cities[o["pickup_city"]]["name"])} → '
                 f'{escape(cities[o["delivery_city"]]["name"])}</div>'
                 f'<div class="cap">{escape(o["id"])} · {o["weight_kg"] / 1000:g} t</div>'
                 + '</div>'
                 f'<div class="side tags">{tag_html}</div></div>')
    html(f'<div class="list unserved">{rows}</div>')


def identity_html(data, colours, tid, with_costs=False):
    truck = data["trucks"][tid]
    facts = (f"{truck['type'].capitalize()} · {truck['capacity_kg']:,} kg · "
             f"starts in {data['cities'][truck['start_city']]['name']}")
    if with_costs:
        facts += f" · €{truck['cost_per_km']}/km"
    html(f'<div class="identity"><span class="ticon big">{truck_svg(34, colours[tid])}</span><div>'
         f'<div class="h3">{escape(tid)}</div><div class="cap" title="{escape(facts)}">{escape(facts)}</div></div></div>')


def numbers_html(data, analysis, tid):
    truck, a = data["trucks"][tid], analysis[tid]
    loaded = f"{100 * a['loaded_km'] / a['km']:.0f}%" if a["km"] else "—"
    cell = lambda k, v: f'<div><div class="ov">{k}</div><div class="vm">{v}</div></div>'
    html('<div class="grid3">'
         + cell("Distance", f'{a["km"]:,}<span class="unit">km</span>')
         + cell("Empty km", f'{a["km"] - a["loaded_km"]:,}<span class="unit">km</span>')
         + cell("Peak load", f"{100 * a['peak_kg'] / truck['capacity_kg']:.0f}%")
         + cell("Cost", f"€{a['cost']:,.0f}") + cell("CO₂", f'{a["co2"]:,.0f}<span class="unit">kg</span>')
         + cell("Orders", f"{a['orders']}") + "</div>")


def timeline_html(data, analysis, colours, tid, done=None):
    """done=None: planner view. done=N: driver view, the first N stops are confirmed."""
    truck, stops = data["trucks"][tid], analysis[tid]["stops"]
    c = colours[tid]
    items = ""
    first = done - 1 if (done is not None and done >= 2) else 0     # driver: keep the last finished stop visible
    folded = (f'<div class="cap" style="margin:0 0 4px 34px">✓ {first} earlier stop{"s" if first != 1 else ""} completed</div>'
              if first else "")
    for i, s in enumerate(stops):
        if i < first:
            continue
        pick = "Pickup" in s["Action"]
        state = "" if done is None else (" done" if i < done else (" current" if i == done else ""))
        items += (f'<div class="stop {"pick" if pick else "drop"}{state}" style="--c:{c}">'
                  f'<div class="node">{"▲" if pick else "▼"}</div><div style="min-width:0">'
                  f'<div class="l1"><span class="body strong">{"Pickup" if pick else "Delivery"} '
                  f'<span class="muted">{escape(s["Order"])}</span></span><span class="cap">+{s["km"]:,} km</span></div>'
                  f'<div class="l2"><span class="body">{escape(s["City"])}</span><span class="load">'
                  f'{meter(s["Load (kg)"], truck["capacity_kg"])}<span class="cap">{compact(s["Load (kg)"])} kg</span>'
                  f'</span></div></div></div>')
    html(f'<div class="section-head"><span class="ov">Stop sequence</span><span class="cap">{len(stops)} stops</span></div>'
         f'{folded}<div class="timeline">{items}</div>')


def next_up_html(data, analysis, tid, done):
    truck, stops = data["trucks"][tid], analysis[tid]["stops"]
    ahead = stops[done:]
    nxt_pick = next((s for s in ahead if "Pickup" in s["Action"]), None)
    nxt_drop = next((s for s in ahead if "Delivery" in s["Action"]), None)
    load_now = stops[done - 1]["Load (kg)"] if done > 0 else 0
    cell = lambda k, v, c: (f'<div><div class="ov">{k}</div><div class="vm" title="{escape(v)}">{escape(v)}</div>'
                            f'<div class="cap">{c}</div></div>')
    html('<div class="grid3">'
         + cell("Next pickup", nxt_pick["City"] if nxt_pick else "None left", f"Order {nxt_pick['Order']}" if nxt_pick else "&nbsp;")
         + cell("Next delivery", nxt_drop["City"] if nxt_drop else "None left", f"Order {nxt_drop['Order']}" if nxt_drop else "&nbsp;")
         + f'<div><div class="ov">Load on board</div><div class="vm">{load_now:,}<span class="unit">kg</span></div>'
           f'<div class="cap">{100 * load_now / truck["capacity_kg"]:.0f}% of {compact(truck["capacity_kg"])} kg</div></div>'
         + "</div>")


def legend_html(show_unplanned=True, show_here=False, colour_by="Load", driver=False, type_counts=None):
    """The map key, the footer of the side panel. Big on purpose: it should read at a glance.
    Load: a wedge that gets darker AND thicker, exactly as the legs on the map do."""
    line = lambda colour, dash="", w=5: (f'<svg width="36" height="12"><line x1="2" y1="6" x2="34" y2="6" stroke="{colour}" '
                                         f'stroke-width="{w}" stroke-linecap="round" {dash}/></svg>')
    standard, cold = line(ROUTE), line(ROUTE_COLD)
    solid, dashed = line(MUTED), line(MUTED, 'stroke-dasharray="5 6" stroke-linecap="butt"', 2.5)
    todo = (f'<svg width="22" height="22"><circle cx="11" cy="11" r="7.5" fill="{STOP_HOLLOW}" stroke="{STOP_EDGE}" stroke-width="6"/>'
            f'<circle cx="11" cy="11" r="7.5" fill="{STOP_HOLLOW}" stroke="{GREEN}" stroke-width="4"/></svg>')
    done = f'<svg width="22" height="22"><circle cx="11" cy="11" r="8" fill="{GREEN}" stroke="{STOP_EDGE}" stroke-width="2"/></svg>'
    red = (f'<span style="display:inline-block;width:16px;height:16px;border-radius:50%;background:{RED};'
           f'box-shadow:0 0 0 1.5px #fff,0 1px 2px rgba(0,0,0,0.3);margin:3px"></span>')
    items = [f'<span>{truck_svg(26)} Truck</span>', f'<span>{dashed} Empty leg</span>']
    if colour_by == "Load":
        n, w = len(LOAD_RAMP), 300 / len(LOAD_RAMP)
        heights = [4 + 18 * i / (n - 1) for i in range(n + 1)]          # thin -> thick, like the map
        wedge = "".join(
            f'<polygon points="{i * w:.1f},{15 - heights[i] / 2:.1f} {(i + 1) * w + 0.6:.1f},{15 - heights[i + 1] / 2:.1f} '
            f'{(i + 1) * w + 0.6:.1f},{15 + heights[i + 1] / 2:.1f} {i * w:.1f},{15 + heights[i] / 2:.1f}" fill="{c}"/>'
            for i, c in enumerate(LOAD_RAMP))
        ticks = "".join(f"<span>{round(100 * i / n)} %</span>" for i in range(n + 1))
        top = (f'<div class="scale"><div class="k">Load on board</div>'
               f'<svg viewBox="0 0 300 30" preserveAspectRatio="none">{wedge}</svg>'
               f'<div class="ticks">{ticks}</div></div>')
    elif driver:
        top = ""
        items = [f'<span>{line(ROUTE_INK)} Your route</span>'] + items
    else:
        counts = type_counts or {}
        rows = "".join(
            f'<div class="type-row"><svg width="44" height="10"><line x1="2" y1="5" x2="42" y2="5" '
            f'stroke="{route_colour({"type": t})}" stroke-width="6" stroke-linecap="round"/></svg>'
            f'{truck_svg(24, route_colour({"type": t}))}<b>{t.capitalize()}</b>'
            f'<span class="n">{counts.get(t, 0)} truck{"s" if counts.get(t, 0) != 1 else ""}</span></div>'
            for t in TRUCK_TYPES)
        top = f'<div class="scale"><div class="k">Truck type</div><div class="types">{rows}</div></div>'
    items.append(f'<span>{todo} Stop to do</span>')
    if show_here:
        items.append(f'<span>{done} Stop done</span>')
    if show_unplanned:
        items.append(f'<span>{red} Unserved order</span>')
    html(f'<div class="legend">{top}<div><div class="k" style="margin-bottom:10px">On the map</div>'
         f'<div class="grid">{"".join(items)}</div></div></div>')


# =============================================================================
# 5. THE MAP
#    OpenStreetMap (toned down); routes coloured by load (violet scale); trucks = neutral icons, stops = green dots,
#    unserved orders = red dots.
# =============================================================================
def map_css():
    return f"""<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700&display=swap');
  html, body {{ height: 100%; margin: 0; }}
  .folium-map, .leaflet-container {{ height: 100vh !important; background: {MAP_BG} !important;
                                     font-family: Manrope, sans-serif; }}
  .leaflet-tile-pane img.leaflet-tile {{ filter: {MAP_TINT}; }}
  .leaflet-overlay-pane path.route {{ mix-blend-mode: {ROUTE_BLEND}; }}
  .leaflet-container::after {{ content: ""; position: absolute; inset: 0; z-index: 350; pointer-events: none;
                               background: {MAP_SHEEN}; }}
  /* Map controls: zoom top-right of the map area as one "− +" pill, scale + credit bottom-left */
  .leaflet-top.leaflet-left {{ top: {INSET}px; left: auto; right: {DOCK_WIDTH + INSET}px; }}
  .leaflet-top.leaflet-left .leaflet-control {{ margin: 0; }}
  .leaflet-control-zoom {{ display: flex; flex-direction: row-reverse; }}
  .leaflet-control-zoom a {{ border-bottom: none !important; border-left: 1px solid {MAP_CONTROL_LINE} !important; }}
  .leaflet-control-zoom a:last-child {{ border-left: none !important; }}
  .leaflet-bottom.leaflet-left {{ left: {INSET}px; bottom: 24px; }}
  .leaflet-control-scale {{ margin: 0 !important; }}
  .leaflet-control-scale-line {{ background: {MAP_CONTROL_BG}; border-color: {MUTED}; color: {TEXT};
                                 font: 600 11px Manrope, sans-serif; }}
  .leaflet-control-scale-line:not(:first-child) {{ display: none; }}   /* km only, no miles */
  .leaflet-interactive:focus, .leaflet-marker-icon:focus, path:focus, .leaflet-container:focus {{ outline: none !important; }}
  .leaflet-bottom.leaflet-right {{ right: auto; left: {INSET}px; }}
  .leaflet-bar {{ border: none !important; border-radius: 999px !important; overflow: hidden;
                  box-shadow: {EDGE}, 0 6px 18px rgba(20,16,40,0.22) !important; }}
  .leaflet-bar a {{ background: {MAP_CONTROL_BG} !important; color: {TEXT} !important;
                    width: 40px !important; height: 36px !important; line-height: 36px !important;
                    border-bottom: 1px solid {MAP_CONTROL_LINE} !important; }}
  .leaflet-control-attribution {{ background: {MAP_CONTROL_BG} !important; border-radius: 8px;
                                  font-size: 10px; color: {MUTED}; margin: 0 0 6px 0 !important; }}
  .leaflet-control-attribution a {{ color: {ACCENT}; }}
  .leaflet-tooltip {{ font-family: Manrope, sans-serif; border: none; border-radius: 10px; background: {TOOLTIP_BG};
                      box-shadow: 0 6px 18px rgba(20,16,40,0.25); color: {TEXT}; }}
  .leaflet-tooltip-top:before {{ border-top-color: {TOOLTIP_BG}; }}
  .leaflet-tooltip-bottom:before {{ border-bottom-color: {TOOLTIP_BG}; }}
  .leaflet-tooltip-left:before {{ border-left-color: {TOOLTIP_BG}; }}
  .leaflet-tooltip-right:before {{ border-right-color: {TOOLTIP_BG}; }}
</style>"""


def curve_points(a, b, bend, steps=24):
    """A gentle arc from a to b that bends to the RIGHT of the direction of travel.
    So A->B and B->A never sit on top of each other, and each truck gets its own bend.
    The lines are schematic (like a metro map): real km always come from the matrix."""
    (lat1, lon1), (lat2, lon2) = a, b
    squeeze = math.cos(math.radians((lat1 + lat2) / 2))     # 1 degree of longitude is shorter than 1 of latitude
    x1, y1, x2, y2 = lon1 * squeeze, lat1, lon2 * squeeze, lat2
    dx, dy = x2 - x1, y2 - y1
    cx, cy = (x1 + x2) / 2 + dy * bend, (y1 + y2) / 2 - dx * bend   # control point, pushed to the right
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t ** 2 * x2
        y = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t ** 2 * y2
        points.append([y, x / squeeze])
    return points


def place_labels(points, ids, names, big=False, map_px=1050):
    """Greedy label thinning: names are tried in order (most important first) and kept only if
    their box (right of the dot) doesn't overlap a name already placed. Works in screen pixels,
    estimated from the area the map will be fitted to (about map_px wide)."""
    if not points:
        return []
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    mid = math.radians((min(lats) + max(lats)) / 2)
    ppd = map_px / max(max(lons) - min(lons), 2.0)            # pixels per degree of longitude
    char, height = (7.0, 16) if big else (6.0, 13)
    placed, keep = [], []
    for (lat, lon), cid, name in zip(points, ids, names):
        x = lon * ppd
        y = -math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))) * ppd   # Mercator, like the map
        box = (x + 8, y - height / 2, x + 12 + char * len(name), y + height / 2)
        if all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in placed):
            placed.append(box)
            keep.append(cid)
    return keep


def build_map(data, analysis, not_in_plan, selected, show_unplanned=True,
              only_selected=False, done_stops=None, here_city=None, unserved_lines=False, colour_by="Load"):
    cities = data["cities"]
    point = lambda cid: [cities[cid]["latitude"], cities[cid]["longitude"]]

    lats = [c["latitude"] for c in cities.values()]
    lons = [c["longitude"] for c in cities.values()]
    # Scale bar (distances matter here); zoom and panning kept to the scenario's part of the world
    m = folium.Map(location=[sum(lats) / len(lats), sum(lons) / len(lons)], zoom_start=5,
                   tiles=MAP_TILES, attr=MAP_CREDIT, zoom_snap=0.25, control_scale=True,
                   min_zoom=3, max_zoom=13)   # no max_bounds: at fleet zoom the box filled the screen, so the map could not be dragged
    m.get_root().header.add_child(folium.Element(map_css()))
    # City names only along the selected truck's route; with all trucks shown they would pile up
    # (hover any city for its name).
    route = []
    if selected in analysis:
        route = [data["trucks"][selected]["start_city"]] + [leg["to"] for leg in analysis[selected]["legs"]]
    if route:          # one truck chosen: zoom to its route, close enough that OSM draws the roads
                     # (OSM shows motorways only from zoom ~7; all of Europe needs zoom ~5)
        lats = [cities[c]["latitude"] for c in route]
        lons = [cities[c]["longitude"] for c in route]
    # Keep the routes clear of the floating buttons (top), side panel (right) and scale (bottom)
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]],
                 padding_top_left=(40, 90), padding_bottom_right=(DOCK_WIDTH + 40, 60))

    def leg_points(leg, detail=False):
        """The real road (data/road_shapes_detail.json), otherwise a gentle curve.
        detail: ~200 m accuracy, for the one truck you zoom in on. Otherwise ~2 km, which is
        invisible at fleet zoom and keeps the page light. Leaflet simplifies further per zoom."""
        a, b = point(leg["from"]), point(leg["to"])
        return roads.shape(a, b, 0.002 if detail else 0.02) or curve_points(a, b, 0.12)

    # ---- Routes: coloured by load (or truck type) -------------------------------------------
    #   all trucks    every route semi-transparent, so busy corridors come out darker
    #   one selected  that truck strong, with a white edge and direction arrows; others faint
    #   driver        only their truck; finished legs turn grey
    # Legs with the same look are drawn as ONE multi-line (folium is slow per object).
    shown = [t for t in sorted(analysis) if analysis[t]["legs"] and (not only_selected or t == selected)]
    draw_order = [t for t in shown if t != selected] + ([selected] if selected in shown else [])
    for tid in draw_order:
        legs = analysis[tid]["legs"]
        is_selected = tid == selected
        truck = data["trucks"][tid]
        colour = route_colour(truck)
        tip = f"{tid} · {truck['type']} · {analysis[tid]['orders']} orders · {analysis[tid]['km']:,} km"
        groups = {}                                    # (colour, strength, loaded, finished) -> leg shapes
        for leg in legs:
            finished = done_stops is not None and is_selected and leg["stop"] <= done_stops
            loaded = leg["load_kg"] > 0
            if not loaded:                             # empty legs: thin grey dashes in both modes
                key = (MUTED, 0.35, False)
            elif colour_by == "Load":                  # violet scale: light = little load, dark = full
                key = (load_colour(leg["load_kg"], truck["capacity_kg"]), 0.95 if selected else 0.75, True)
            elif colour_by == "Route":                 # driver: their one route, one colour
                key = (ROUTE_INK, 0.9, True)
            else:
                key = (colour, 0.9, True)
            groups.setdefault(key + (finished,), []).append(leg_points(leg, is_selected))

        def line(shapes, **style):
            path = folium.PolyLine(shapes, smooth_factor=1.5, **style)
            path.options["className"] = "route"        # blended in CSS: overlaps darken / glow
            return path.add_to(m)

        for (colour_, alpha, loaded, finished), shapes in groups.items():
            dash = None if loaded else "4 6"
            if selected is None:                       # all trucks: thin lines with a thin edge
                width = LOAD_WEIGHT[LOAD_RAMP.index(colour_)] if colour_ in LOAD_RAMP else 2.2
                if loaded:                             # thin edge in the map's background colour
                    folium.PolyLine(shapes, color=CASING, weight=width + 2, opacity=CASING_OPACITY * 0.8,
                                    smooth_factor=1.5).add_to(m)
                if ROUTE_GLOW and loaded:
                    line(shapes, color=colour_, weight=width + 5, opacity=alpha * 0.22)
                line(shapes, color=colour_, weight=width if loaded else 1.2, opacity=alpha,
                     dash_array=dash, tooltip=tip)
            elif not is_selected:                      # someone else's route: barely there
                line(shapes, color=colour_, weight=1.5, opacity=0.10, dash_array=dash, tooltip=tip)
            elif finished:                             # driver: already driven
                folium.PolyLine(shapes, color=MUTED, weight=4, opacity=0.5, dash_array=dash, smooth_factor=1.5).add_to(m)
            else:                                      # the selected truck: strong, with an edge
                folium.PolyLine(shapes, color=CASING, weight=9, opacity=CASING_OPACITY, smooth_factor=1.5).add_to(m)
                folium.PolyLine(shapes, color=colour_, weight=5, opacity=max(alpha, 0.45) if loaded else 0.8,
                                dash_array=dash, tooltip=tip, smooth_factor=1.5).add_to(m)
        if is_selected:                                # direction arrows, one per leg still to drive
            for leg in legs:
                if done_stops is not None and leg["stop"] <= done_stops:
                    continue
                arrow = folium.PolyLine(leg_points(leg, True), opacity=0, weight=1).add_to(m)
                PolyLineTextPath(arrow, "►", center=True, offset=5,
                                 attributes={"fill": TRUCK_ICON if colour_by == "Load" else colour, "font-size": "15"}).add_to(m)

    # ---- Green dots: stops of the orders trucks take. Hollow = still to do, filled = done -------
    stops_at = {}                                      # city -> [(text, done)]
    for tid in shown:
        if selected is not None and tid != selected:
            continue
        for i, (row, cid) in enumerate(zip(analysis[tid]["stops"], analysis[tid]["stop_cities"])):
            done = done_stops is not None and tid == selected and i < done_stops
            what = "Pickup" if "Pickup" in row["Action"] else "Delivery"
            stops_at.setdefault(cid, []).append((f"{what} {row['Order']} ({tid}){' ✓' if done else ''}", done))
    ring = {}                                          # city -> radius of its green ring (px)
    for cid, items in stops_at.items():
        all_done = all(d for _, d in items)
        radius = (5 + min(len(items), 8) * 0.5) if selected else (2.5 + min(len(items), 8) * 0.3)
        ring[cid] = radius
        folium.CircleMarker(point(cid), radius=radius, color=STOP_EDGE, weight=(3 if selected else 2) + 2,
                            fill=False, opacity=0.9, interactive=False).add_to(m)   # edge under the green ring
        folium.CircleMarker(
            point(cid), radius=radius,
            color=GREEN, weight=3 if selected else 2,
            fill=True, fill_color=GREEN if all_done else STOP_HOLLOW, fill_opacity=1,
            tooltip=f"<b>{cities[cid]['name']}</b><br>" + "<br>".join(t for t, _ in items[:12])
                    + (f"<br>+{len(items) - 12} more" if len(items) > 12 else ""),
        ).add_to(m)

    # ---- Red badges: orders no truck takes, at the pickup city. ONE marker per city:
    #      no green ring there -> the red dot sits exactly on the city;
    #      a green ring there  -> a small red badge clipped to the ring's lower-right edge.
    #      Truck icons stand above the city, so nothing covers anything. Number = how many orders.
    by_city = {}
    if show_unplanned:
        for o in not_in_plan:
            by_city.setdefault(o["pickup_city"], []).append(o)
        for cid, orders in by_city.items():
            listing = "<br>".join(f"{o['id']}: → {cities[o['delivery_city']]['name']}, {o['weight_kg']:,} kg"
                                  f"{', needs ' + o['required_truck_type'] if o.get('required_truck_type') else ''}"
                                  for o in orders)
            count = str(len(orders)) if len(orders) > 1 else ""
            size = (14 if count else 11) + (3 if selected else 0)
            off = round(ring[cid] * 0.75 + 2) if cid in ring else 0    # 0 = centred on the city
            folium.Marker(point(cid), icon=folium.DivIcon(
                icon_size=(size, size), icon_anchor=(size // 2 - off, size // 2 - off),
                html=f'<div style="width:{size}px;height:{size}px;border-radius:50%;background:{RED};'
                     f'box-shadow:0 0 0 1.5px #fff,0 1px 3px rgba(0,0,0,0.35);color:#fff;'
                     f'font:800 {size - 5}px/{size}px Manrope,sans-serif;text-align:center">{count}</div>',
            ), z_index_offset=900, tooltip=f"<b>{cities[cid]['name']}: {len(orders)} order{'s' if len(orders) != 1 else ''} "
                       f"unserved</b><br>{listing}").add_to(m)
        if unserved_lines:                             # "Unserved orders" tab open: show where each would go.
            for o in not_in_plan:                      # straight dashed lines = demand, not a driven road
                a, b = point(o["pickup_city"]), point(o["delivery_city"])
                tip = (f"<b>{o['id']} unserved</b><br>{cities[o['pickup_city']]['name']} → "
                       f"{cities[o['delivery_city']]['name']}, {o['weight_kg']:,} kg")
                folium.PolyLine([a, b], color=RED, weight=2, opacity=0.75, dash_array="2 6", tooltip=tip).add_to(m)
                folium.CircleMarker(b, radius=5, color=RED, weight=2, fill=True, fill_color="#fff",
                                    fill_opacity=1, tooltip=tip).add_to(m)

    # ---- City names: OUR names (the base map prints local scripts: Cyrillic, Greek, ...).
    #      One truck: every city on its route. Fleet: every city with stops or unserved orders,
    #      smaller. Names that would overlap another name are skipped (hover a dot for its name).
    wanted = route if route else sorted(set(stops_at) | set(by_city), key=lambda c: -len(stops_at.get(c, [])))
    for cid in place_labels([point(c) for c in dict.fromkeys(wanted)], list(dict.fromkeys(wanted)),
                            [cities[c]["name"] for c in dict.fromkeys(wanted)], big=bool(route)):
        folium.Marker(point(cid), interactive=False, icon=folium.DivIcon(
            icon_size=(160, 18), icon_anchor=(-9, 9 if route else 8),
            html=f'<div style="color:{LABEL_TEXT};font-size:{12 if route else 10.5}px;font-weight:{700 if route else 600};'
                 f'white-space:nowrap;font-family:Manrope,sans-serif;pointer-events:none;opacity:{1 if route else 0.85};'
                 f'text-shadow:0 0 3px {LABEL_HALO},0 0 3px {LABEL_HALO},0 0 6px {LABEL_HALO}">{cities[cid]["name"]}</div>',
        )).add_to(m)

    # ---- Trucks: a plain truck icon standing on its city (start, or where the driver is now) -----
    # Several trucks at one city become one icon with "×N", so no icon sits off its real position.
    at_city = {}
    for tid in shown:
        if selected is not None and tid != selected:
            continue
        where = here_city if (here_city is not None and tid == selected) else data["trucks"][tid]["start_city"]
        at_city.setdefault(where, []).append(tid)
    for where, tids in at_city.items():
        text = f"×{len(tids)}" if len(tids) > 1 and selected not in tids else ""
        label = (f'<span style="position:absolute;left:{30 if selected else 22}px;top:{6 if selected else 2}px;font:800 12px Manrope,sans-serif;'
                 f'color:{TRUCK_ICON};white-space:nowrap;text-shadow:0 0 3px {LABEL_HALO},0 0 3px {LABEL_HALO},0 0 5px {LABEL_HALO}">{text}</span>'
                 if text else "")
        state = "now here" if where == here_city else "start here"
        px = 28 if selected else 20                    # fleet view: small icons, the routes are the picture
        folium.Marker(point(where), icon=folium.DivIcon(
            icon_size=(px, px), icon_anchor=(px // 2, px + 2),  # bottom-centre of the icon just above the city dot
            html=f'<div style="position:relative;width:{px}px;height:{px}px;'
                 f'filter:drop-shadow(0 2px 2px rgba(0,0,0,0.3))">{truck_svg(px)}{label}</div>',
        ), tooltip=f"<b>{cities[where]['name']}</b> · {state}<br>"
                   + "<br>".join(f"{t} · {data['trucks'][t]['type']}" for t in tids),
            z_index_offset=1000,                        # always above city names and dots
        ).add_to(m)
    return m


# =============================================================================
# 6. THE PAGE
#    Streamlit runs this whole file top to bottom on every click.
#    The role tabs in the header decide who is using the app, and so what they see.
# =============================================================================
st.set_page_config(page_title=BRAND_NAME, page_icon="🚚", layout="wide", initial_sidebar_state="collapsed")

if st.get_option("theme.base") != "light":
    st.warning("The light theme wasn't loaded. Start the app from the repo root: "
               "`python -m streamlit run dashboard/app.py`")

# Theme: light by default. Remembered in the session (survives role and truck changes)
# and in the page address (?theme=dark), so it also survives a page refresh.
if "theme" not in st.session_state:
    st.session_state.theme = "dark" if st.query_params.get("theme") == "dark" else "light"


def toggle_theme():
    st.session_state.theme = "dark" if st.session_state.theme == "light" else "light"
    st.query_params["theme"] = st.session_state.theme


apply_theme(st.session_state.theme)
inject_css()
html(f"""<style>
  /* the data menu in the header looks like a status chip */
  .st-key-data_menu button {{ border-radius: 999px; background: {FLOAT_BG};
        border: 1px solid {PANEL_BORDER}; box-shadow: {EDGE}, 0 4px 14px rgba(20,16,40,0.16); padding: 8px 16px; min-height: 0; }}
  .st-key-data_menu button p {{ font-size: 0.8rem; font-weight: 600; color: {TEXT}; }}
  .st-key-data_menu {{ display: flex; justify-content: flex-end; }}
</style>""")

if st.session_state.get("role") not in ROLE_PRESETS:     # first visit, or "Manager" from before
    st.session_state.role = "Dispatcher"

scenario = SCENARIO
if scenario not in list_scenarios():
    st.error(f"No scored plans for {scenario} in {DB_PATH}. Run the solver first: "
             f"`cd solver && python run.py {scenario}`.")
    st.stop()


def refresh():
    """Re-read the DB (new fetches and solver runs) and fetch road shapes for any new legs."""
    st.cache_data.clear()
    roads.reset()
    try:
        added = roads.fill([scenario], max_new=60)    # only legs not cached yet; ~1 s each
        if added < 0:                                 # too many for a button click: do it in a terminal
            st.session_state.refresh_note = (f"Updated · {-added} roads missing (drawn as curves): "
                                             f"run python3 dashboard/roads.py {scenario}")
        else:
            st.session_state.refresh_note = (f"Updated · {added} new road{'s' if added != 1 else ''}"
                                             if added else "Updated")
    except Exception as error:                        # offline: still show the new plans, drawn as curves
        st.session_state.refresh_note = f"Updated (roads not fetched: {error.__class__.__name__})"
    st.session_state.refreshed_at = pd.Timestamp.now().strftime("%H:%M")

# The browser shows an iframe's title as a hover tooltip ("streamlit_folium.st_folium" over the map).
# Move it to aria-label: screen readers keep a name, the mouse gets no tooltip.
st.html("""<script>
(() => {
  if (window.__noIframeTitles) return; window.__noIframeTitles = true;
  const fix = () => document.querySelectorAll("iframe[title]").forEach(f => {
    f.setAttribute("aria-label", f.title === "streamlit_folium.st_folium" ? "Map" : f.title);
    f.removeAttribute("title"); });
  fix(); new MutationObserver(fix).observe(document.body, {childList: true, subtree: true});
})();
</script>""", unsafe_allow_javascript=True)

# ---- View menu: a ☰ button at the top of the side panel; it opens the list of views -------
def set_role(name):
    st.session_state.role = name


with st.container(key="rolebar", horizontal=True, vertical_alignment="center"):
    with st.container(key="role_menu", width="content"):
        with st.popover("", icon=":material/menu:", help="Switch view"):
            with st.container(key="role_options"):
                for name, (icon, hint) in ROLE_INFO.items():
                    st.button(name, key=f"role_{name}", icon=icon, on_click=set_role, args=(name,),
                              type="tertiary", help=hint, width="stretch")
                now = st.session_state.role                 # current view: tinted, with a tick on the right
                html(f'<style>.st-key-role_{now} button {{ background: color-mix(in srgb, {ACCENT} 14%, transparent) !important; }}'
                     f'.st-key-role_{now} button p {{ color: {ACCENT} !important; font-weight: 700 !important; }}'
                     f'.st-key-role_{now} button span {{ color: {ACCENT} !important; }}'
                     f'.st-key-role_{now} button::after {{ content: "✓"; margin-left: auto; color: {ACCENT}; font-weight: 800; }}</style>')
    html(f'<div class="role-now"><div class="k">View</div><div class="v">{st.session_state.role}</div></div>')

# ---- Top-left of the map: brand · refresh · status · theme, as floating pills ---------------
with st.container(key="topbar", horizontal=True, vertical_alignment="center", gap="small", width="content"):
    brand_html()
    with st.container(key="data_menu", width="content"):
        plans = list_plans(scenario)                   # best valid plan first
        plan_file = plans[0]
        when = st.session_state.get("refreshed_at")
        st.button(f"Refresh · {when}" if when else "Refresh", icon=":material/refresh:", on_click=refresh,
                  help=f"Reload the newest data and solver results for {scenario}. "
                       f"Showing the best plan: {plan_file}. " + st.session_state.get("refresh_note", ""))
    head_chips = st.container(width="content")
    going_to = "dark" if st.session_state.theme == "light" else "light"
    st.button("", key="theme_toggle", on_click=toggle_theme,
              icon=":material/dark_mode:" if going_to == "dark" else ":material/light_mode:",
              help=f"Switch to {THEME_NAMES[going_to]}")
role = st.session_state.role
is_driver = role == "Driver"

try:
    data = load_scenario(scenario)
    plan = load_plan(scenario, plan_file)
    official = load_official(scenario, plan_file)
except Exception as error:                     # show a readable message instead of crashing
    st.error(f"Couldn't read the data: {error}")
    st.stop()

analysis, not_in_plan, problems = analyse_plan(data, plan)
colour_by = "Route" if role == "Driver" else st.session_state.get("route_colour", "Load")   # toggle in the legend
colours = truck_colours(data, colour_by)
show = set(ROLE_PRESETS[role])
show_numbers = "Fleet numbers" in show
show_map = "Map" in show

with head_chips:
    chips_html(problems, official)


# ---- Driver progress: how many stops the driver has confirmed -------------------------------
def progress_key(tid):
    return f"stops_done_{scenario}_{plan_file}_{tid}"    # separate progress per plan and truck


def stop_done(key, total):
    st.session_state[key] = min(st.session_state.get(key, 0) + 1, total)


def stop_back(key):
    st.session_state[key] = max(st.session_state.get(key, 0) - 1, 0)


# ---- Layout -----------------------------------------------------------------------------
#   Dispatcher / Driver: the map is the whole background, the side panel floats on the right.
#   Manager: no map; the full number strip on top and the economics underneath.
if show_map:
    # The page itself lets clicks through to the map; only the floating panels catch them.
    html("""<style>
      [data-testid="stMain"] { pointer-events: none; }
      .st-key-topbar, .st-key-rolebar, .st-key-dock, .st-key-mapbox { pointer-events: auto; }
    </style>""")
    map_holder = st.container(key="mapbox")          # filled last, once the truck choice is known
    dock = st.container(key="dock")
else:
    if show_numbers:
        with st.container(key="ribbon_slot"):
            ribbon_html(data, analysis, not_in_plan, official, baseline_score(scenario))
    dock = st.container(key="dock_static")

used_trucks = [t for t in sorted(analysis) if analysis[t]["orders"]]
# Truck picker: the id first, then only what you choose a truck by (type, capacity in tonnes)
labels = {tid: f"{tid}  ·  {data['trucks'][tid]['type']} · {data['trucks'][tid]['capacity_kg'] / 1000:g} t"
          for tid in analysis}
truck_options = used_trucks if is_driver else ["All trucks"] + used_trucks
selected = None

# ---- Side panel: what is inside depends on the role -----------------------------------------
with dock:
    head = st.empty()
    choice = st.selectbox("Your truck" if is_driver else "Truck", truck_options, key=f"truck_{role}",
                          format_func=lambda t: labels.get(t, t), label_visibility="collapsed")
    selected = None if choice == "All trucks" else choice
    if selected:                                   # the panel's light picks up the truck's colour
        html(f"<style>.st-key-dock, .st-key-dock_static, .st-key-picker {{ --truck: {colours[selected]}; }}</style>")
    done_stops = st.session_state.get(progress_key(selected), 0) if (is_driver and selected) else None

    if is_driver:
        total = len(analysis[selected]["stops"])
        meta = f"Stop {done_stops + 1} of {total}" if done_stops < total else f"All {total} stops done ✓"
        head.markdown(f'<div class="dock-head"><div class="h2">Your route</div><div class="cap">{meta}</div></div>',
                      unsafe_allow_html=True)
    elif role == "Manager":
        head.markdown('<div class="dock-head"><div class="h2">Costs per truck</div>'
                      '<div class="cap">cost and CO₂ per truck</div></div>', unsafe_allow_html=True)
    else:
        pass                                       # no heading: the "Trucks (22)" tab already says it

    with st.container(key="dock_scroll"):
        if problems and not is_driver:
            with st.expander(f"{len(problems)} rule problem(s): each violation costs 20 points", icon=":material/warning:"):
                for p in problems:
                    st.markdown(f"- {p}")

        if is_driver:
            identity_html(data, colours, selected)
            next_up_html(data, analysis, selected, done_stops)
            html(f'<div class="progress"><i style="width:{100 * done_stops / max(total, 1):.0f}%"></i></div>')
            back_col, done_col = st.columns([1, 1.5], gap="small")
            key = progress_key(selected)
            with back_col:
                st.button("◀ Back", key=f"back_{selected}", on_click=stop_back, args=(key,),
                          disabled=done_stops == 0, width="stretch")
            with done_col:
                st.button("✓ Stop done", key=f"done_{selected}", on_click=stop_done, args=(key, total),
                          disabled=done_stops >= total, type="primary", width="stretch")
            html('<div class="hair"></div>')
            timeline_html(data, analysis, colours, selected, done=done_stops)

        elif role == "Manager":
            # Fleet-wide first; one truck's details only on demand, underneath
            fleet_list_html(data, analysis, colours, role, highlight=selected)
            if selected:
                html('<div class="hair"></div>')
                identity_html(data, colours, selected, with_costs=True)
                numbers_html(data, analysis, selected)
            html('<div class="hair"></div>')
            not_served_html(data, not_in_plan, explain_unserved(scenario, plan_file) if not_in_plan else None)

        else:   # Dispatcher: the fleet and what is left over, or one truck's route
            if selected is None:
                summary_html(data, analysis, official, baseline_score(scenario))
                html('<div class="hair"></div>')
                trucks_tab = f"Trucks ({len(used_trucks)})"
                tabs = [trucks_tab] + ([f"Unserved orders ({len(not_in_plan)})"] if not_in_plan else [])
                tab = st.segmented_control("List", tabs, key="dock_tab", default=trucks_tab,
                                           label_visibility="collapsed") or trucks_tab
                if tab == trucks_tab:
                    fleet_list_html(data, analysis, colours, role)
                else:
                    not_served_html(data, not_in_plan, explain_unserved(scenario, plan_file))
            else:
                identity_html(data, colours, selected)
                numbers_html(data, analysis, selected)
                html('<div class="hair"></div>')
                timeline_html(data, analysis, colours, selected)
    if show_map:
        legend_slot = st.container(key="legend_slot")   # panel footer, filled once the map is drawn

# ---- The map ---------------------------------------------------------------------------
if show_map:
    done_stops = st.session_state.get(progress_key(selected), 0) if (is_driver and selected) else None
    here = None
    if is_driver and selected:
        stop_cities = analysis[selected]["stop_cities"]
        here = data["trucks"][selected]["start_city"] if done_stops == 0 else stop_cities[done_stops - 1]
    with map_holder:
        fleet_map = build_map(data, analysis, not_in_plan, selected,
                              show_unplanned="Orders not in plan" in show,
                              only_selected=is_driver, done_stops=done_stops, here_city=here,
                              colour_by=colour_by)
        st_folium(fleet_map, height=800, use_container_width=True, returned_objects=[], key="fleet_map")
    with legend_slot, st.expander("Map key", expanded=True, icon=":material/map:"):
        if not is_driver:                              # a driver has one route: nothing to switch
            st.segmented_control("Colour routes by", ["Load", "Truck type"], key="route_colour", default="Load",
                                 required=True)
        legend_html(show_unplanned="Orders not in plan" in show, show_here=here is not None,
                    colour_by=colour_by, driver=is_driver,
                    type_counts={t: sum(data["trucks"][u]["type"] == t for u in used_trucks) for t in TRUCK_TYPES})
