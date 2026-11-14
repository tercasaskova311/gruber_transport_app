"""Configuration: base URL and API key from environment or a git-ignored .env file.

The API key is never printed or logged.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"
API_LOG_DIR = ROOT / "api_log"

_KEYS = ("GRUBER_BASE_URL", "GRUBER_API_KEY")


def _load_dotenv() -> dict[str, str]:
    p = ROOT / ".env"
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8-sig")
    out: dict[str, str] = {}
    # Robust to missing newlines between entries: split on known key names.
    pattern = re.compile(r"(%s)\s*=" % "|".join(_KEYS))
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        val = text[m.end():end].strip().strip('"').strip("'").strip()
        out[m.group(1)] = val
    return out


def get(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v.strip()
    return _load_dotenv().get(name)


def base_url() -> str:
    """Return the API root ending in /Hackaton2026 (no trailing slash)."""
    url = get("GRUBER_BASE_URL")
    if not url:
        raise RuntimeError("GRUBER_BASE_URL not set (env var or .env)")
    url = url.strip()
    for marker in ("/swagger", "/Hackaton2026"):
        i = url.find(marker)
        if i >= 0:
            url = url[:i]
    url = url.rstrip("/")
    if not url.endswith("/Hackaton2026"):
        url += "/Hackaton2026"
    return url


def api_key() -> str:
    k = get("GRUBER_API_KEY")
    if not k:
        raise RuntimeError("GRUBER_API_KEY not set (env var or .env)")
    return k
