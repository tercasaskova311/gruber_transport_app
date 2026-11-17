"""Sign-in for the dashboard: who you are decides what you see.

Roles
    Dispatcher  the whole fleet, every route and every unserved order; can preview the driver view
    Driver      one truck only (the one on the account), stop by stop

Accounts come from Streamlit secrets (.streamlit/secrets.toml, git-ignored, or the hosting
platform's secrets settings):

    [auth.users.anna]
    name = "Anna Rossi"
    role = "Dispatcher"
    password_hash = "pbkdf2_sha256$200000$<salt>$<hash>"

    [auth.users.marco]
    name = "Marco"
    role = "Driver"
    truck = "T05"
    password_hash = "..."

Make a hash with:  python dashboard/auth.py '<password>'

Without secrets the app falls back to the two DEMO_USERS below, and the sign-in screen shows
their passwords. That is on purpose: the public demo should be one click away. It is demo-grade
access control (hashed passwords, a short lockout after failed attempts), not user management.

This module has no Streamlit import at the top, so the logic is unit-tested in tests/test_auth.py.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
from dataclasses import dataclass

ROLES = ("Dispatcher", "Driver")
ITERATIONS = 200_000
MAX_FAILURES = 5          # failed attempts in a row before a pause
LOCKOUT_S = 30            # length of that pause


@dataclass(frozen=True)
class User:
    username: str
    name: str
    role: str
    truck: str | None = None      # drivers only: the truck they drive

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or self.username[:2].upper()


# Public demo accounts. The passwords are shown on the sign-in screen while no secrets are set.
DEMO_PASSWORDS = {"dispatcher": "dispatch-demo", "driver": "driver-demo"}
DEMO_USERS = {
    "dispatcher": dict(name="Demo Dispatcher", role="Dispatcher",
                       password_hash="pbkdf2_sha256$200000$bbe1f2b5e9f9a2db3bbe37ac4b9898fe$"
                                     "9c571799f5ffe945828cabbf8ca1fe8d0ac8c93c49dbea038522586de3537c8c"),
    "driver": dict(name="Demo Driver", role="Driver", truck="T05",
                   password_hash="pbkdf2_sha256$200000$b0571c880d03436c82d111b9e8e34944$"
                                 "0b166c99fe9e3b368ac2d83be85e0bbf6d1175878803781a58ce5adc4afe885b"),
}


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt if salt is not None else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def load_users(secrets=None) -> tuple[dict[str, dict], bool]:
    """(accounts, is_demo). Accounts from secrets["auth"]["users"] if present, else DEMO_USERS."""
    try:
        users = secrets["auth"]["users"] if secrets is not None else None
    except (KeyError, TypeError, FileNotFoundError):
        users = None
    except Exception:          # st.secrets raises its own error when no secrets file exists
        users = None
    if users:
        return {str(k).lower(): dict(v) for k, v in users.items()}, False
    return DEMO_USERS, True


def authenticate(username: str, password: str, users: dict[str, dict]) -> User | None:
    """The User if the username exists, the password matches and the account is valid; else None."""
    key = (username or "").strip().lower()
    account = users.get(key)
    if account is None:
        hash_password(password or "", salt=b"0" * 16)        # same work as a real check: no timing hint
        return None
    if not verify_password(password or "", account.get("password_hash", "")):
        return None
    role = account.get("role")
    if role not in ROLES or (role == "Driver" and not account.get("truck")):
        return None                                          # misconfigured account: refuse, don't guess
    return User(username=key, name=account.get("name") or key, role=role, truck=account.get("truck"))


class Throttle:
    """Pause sign-in for LOCKOUT_S after MAX_FAILURES wrong passwords in a row (per browser session)."""

    def __init__(self, state: dict, now=time.monotonic):
        self.state, self.now = state, now

    def locked_for(self) -> int:
        until = self.state.get("auth_locked_until", 0)
        return max(0, int(round(until - self.now())))

    def failure(self) -> None:
        n = self.state.get("auth_failures", 0) + 1
        self.state["auth_failures"] = n
        if n >= MAX_FAILURES:
            self.state["auth_locked_until"] = self.now() + LOCKOUT_S
            self.state["auth_failures"] = 0

    def success(self) -> None:
        self.state["auth_failures"] = 0
        self.state.pop("auth_locked_until", None)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python dashboard/auth.py '<password>'   (prints a hash for secrets.toml)")
    print(hash_password(sys.argv[1]))
