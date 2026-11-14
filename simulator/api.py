"""HTTP client for the Gruber Hackaton2026 API.

Safety rules (see README):
- GET /Scenarios... and Validate are free.
- Simulate / Score always require an interactive y/n confirmation that shows what
  will be sent (single call) or an Approval obtained from confirm_batch().
- scenario_competitive additionally requires i_am_sure=True (CLI flag --i-am-sure).
Every Validate/Simulate/Score request+response is saved under data/api_responses/.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from . import config

COMPETITIVE = "scenario_competitive"
RESP_DIR = config.DATA_DIR / "api_responses"


class SafetyError(RuntimeError):
    pass


@dataclass
class Approval:
    """A user-confirmed batch: scenario, endpoint kinds and max number of calls."""
    scenario: str
    kinds: frozenset
    remaining: int
    i_am_sure: bool = False
    used: int = 0

    def consume(self, scenario: str, kind: str) -> None:
        if scenario != self.scenario:
            raise SafetyError(f"approval is for {self.scenario}, not {scenario}")
        if kind not in self.kinds:
            raise SafetyError(f"approval does not cover {kind}")
        if self.remaining <= 0:
            raise SafetyError("approval exhausted; ask again")
        self.remaining -= 1
        self.used += 1


def _ask_yes(prompt: str) -> bool:
    sys.stdout.write(prompt + " [y/N]: ")
    sys.stdout.flush()
    line = sys.stdin.readline()
    ans = line.strip().lower()
    print()
    return ans in ("y", "yes")


def _plan_summary(plan: dict) -> str:
    parts = []
    for t, stops in plan.items():
        orders = sorted({s.get("order") for s in stops if isinstance(s, dict)})
        parts.append(f"{t}:{len(stops)} stops/{len(orders)} orders")
    return ", ".join(parts) if parts else "(empty plan)"


def _check_competitive(scenario: str, i_am_sure: bool) -> None:
    if scenario == COMPETITIVE and not i_am_sure:
        raise SafetyError(
            "Refusing Simulate/Score on scenario_competitive without --i-am-sure "
            "(only 3 calls each allowed in total).")


def confirm_batch(scenario: str, kinds: set[str], n_calls: int, description: str,
                  plans: list[dict] | None = None, i_am_sure: bool = False) -> Approval:
    """Print what will be sent and ask y/n once. Raises SafetyError on 'no'."""
    _check_competitive(scenario, i_am_sure)
    print("=" * 72)
    print(f"ABOUT TO CALL {'/'.join(sorted(kinds))} on {scenario}: {n_calls} call(s)")
    print(f"Reason: {description}")
    if plans is not None:
        dump = RESP_DIR / f"pending_{scenario}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        dump.parent.mkdir(parents=True, exist_ok=True)
        dump.write_text(json.dumps(plans, indent=1))
        for i, p in enumerate(plans):
            print(f"  plan[{i}]: {_plan_summary(p)}")
        print(f"Full payloads written to {dump}")
    print("=" * 72)
    if not _ask_yes("Send these requests?"):
        raise SafetyError("user declined")
    return Approval(scenario, frozenset(kinds), n_calls, i_am_sure)


class Client:
    def __init__(self, base_url: str | None = None, timeout: float = 60.0):
        self.base = (base_url or config.base_url()).rstrip("/")
        self.timeout = timeout
        self.s = requests.Session()

    # ---------------- public GETs ----------------
    def _get(self, path: str, raw: bool = False):
        r = self.s.get(self.base + path, timeout=self.timeout)
        r.raise_for_status()
        return r.text if raw else r.json()

    def scenarios(self):
        return self._get("/Scenarios")

    def cities(self, sid):
        return self._get(f"/Scenarios/{sid}/Cities")

    def trucks(self, sid):
        return self._get(f"/Scenarios/{sid}/Trucks")

    def orders(self, sid):
        return self._get(f"/Scenarios/{sid}/Orders")

    def distance_matrix(self, sid):
        return self._get(f"/Scenarios/{sid}/DistanceMatrix")

    def distance_matrix_csv(self, sid):
        return self._get(f"/Scenarios/{sid}/DistanceMatrix/csv", raw=True)

    def sample_plan(self, sid):
        return self._get(f"/Scenarios/{sid}/SamplePlan")

    # ---------------- team ----------------
    def team(self):
        r = self.s.get(self.base + "/Team", headers=self._auth(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---------------- submissions ----------------
    def _auth(self) -> dict:
        return {"X-Api-Key": config.api_key()}

    def _post(self, kind: str, sid: str, plan: dict) -> dict:
        r = self.s.post(f"{self.base}/Submissions/{sid}/{kind}", json=plan,
                        headers=self._auth(), timeout=self.timeout)
        try:
            body = r.json()
        except ValueError:
            body = {"_raw": r.text}
        rec = {"kind": kind, "scenario": sid, "status": r.status_code,
               "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "plan": plan, "response": body}
        RESP_DIR.mkdir(parents=True, exist_ok=True)
        fn = RESP_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time()*1000)%1000:03d}_{sid}_{kind}.json"
        fn.write_text(json.dumps(rec, indent=1))
        if r.status_code >= 400:
            raise requests.HTTPError(f"{kind} {sid} -> {r.status_code}: {str(body)[:500]}")
        return body

    def validate(self, sid: str, plan: dict) -> dict:
        return self._post("Validate", sid, plan)

    def _guarded(self, kind: str, sid: str, plan: dict, approval: Approval | None,
                 i_am_sure: bool) -> dict:
        _check_competitive(sid, i_am_sure or (approval is not None and approval.i_am_sure))
        if approval is None:
            print("=" * 72)
            print(f"ABOUT TO CALL {kind} on {sid} (1 call). Payload:")
            print(json.dumps(plan, indent=1))
            print("=" * 72)
            if not _ask_yes(f"Send {kind}?"):
                raise SafetyError("user declined")
        else:
            approval.consume(sid, kind)
        return self._post(kind, sid, plan)

    def simulate(self, sid: str, plan: dict, approval: Approval | None = None,
                 i_am_sure: bool = False) -> dict:
        return self._guarded("Simulate", sid, plan, approval, i_am_sure)

    def score(self, sid: str, plan: dict, approval: Approval | None = None,
              i_am_sure: bool = False) -> dict:
        return self._guarded("Score", sid, plan, approval, i_am_sure)
