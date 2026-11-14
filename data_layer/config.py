"""Shared settings for the data layer. Edit here, not in the scripts."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- API -------------------------------------------------------------------
BASE_URL = os.environ.get(
    "GRUBER_API", "https://hackathon-challenge.gruber-logistics.dev/Hackaton2026"
).rstrip("/")

# Endpoint templates. If the real paths differ (e.g. /Trucks?scenarioId=...),
# change them here and nothing else needs to move.
URL_SCENARIOS = "/Scenarios"
URL_CITIES = "/Scenarios/{sid}/Cities"
URL_TRUCKS = "/Scenarios/{sid}/Trucks"
URL_ORDERS = "/Scenarios/{sid}/Orders"
URL_DISTANCES = "/Scenarios/{sid}/DistanceMatrix/csv"

HTTP_TIMEOUT_S = 30
HTTP_RETRIES = 4          # attempts per request, with exponential backoff

# --- Storage ---------------------------------------------------------------
# data/ at the repo root: hackathon.duckdb + snapshots data/<scenario>/<snapshot_id>/
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE.parent / "data"))
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "hackathon.duckdb"))

# --- Problem rules (keep in sync with prepare.sql macros) -------------------
SPEED_KMH = 70            # drive_minutes = ceil(km * 60 / 70)
SERVICE_MIN = 30          # per stop (pickup or delivery)
DAY1_START_HOUR = 6       # minute 0 = Day 1 06:00
