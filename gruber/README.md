# `gruber` — API client, data loader and exact local simulator

This package is the shared base for every solver. It can:

- download scenario data from the hackathon API and save it as snapshots,
- load a snapshot into Python objects,
- **simulate and score any plan locally, exactly like the API does** (verified
  field by field on 156 Simulate/Score responses, see [`docs/semantics.md`](../docs/semantics.md)).

Use the local simulator for all development. Only the final plan needs to go to the API.

## Setup

```powershell
pip install -r requirements.txt        # requests, numpy, pytest, duckdb
```

Create a `.env` file in the project root (it is git-ignored, never commit it):

```
GRUBER_BASE_URL=https://hackathon-challenge.gruber-logistics.dev
GRUBER_API_KEY=<team key>
```

The scenario endpoints are public; the key is only needed for Validate / Simulate / Score.

## Modules

| File | What it does |
|---|---|
| `config.py` | Reads the base URL and API key from env vars or `.env`. Never prints the key. |
| `api.py` | HTTP client for all endpoints. Simulate / Score are guarded (see below). |
| `loader.py` | **The only way solvers get data.** Returns a `Scenario` object. |
| `simulator.py` | Exact copy of the API's Validate, Simulate and Score. |
| `cli.py` | Command line: `local`, `validate`. |

## Using it from code

```python
from gruber import loader, simulator

sc = loader.load("scenario_small")        # latest snapshot; or load(sid, "20261113_192945")

sc.trucks          # list[Truck]: id, start (city index), capacity, type, cost_per_km, co2_per_km
sc.orders          # list[Order]: id, p / d (city indices), weight, required_type,
                   #   pw / dw (pickup/delivery window as (from, to) or None), value
sc.dist[i, j]      # numpy int matrix, km between city indices i and j
sc.order_by_id["O001"], sc.truck_by_id["T01"]

plan = {"T01": [{"action": "pickup", "order": "O001"},
                {"action": "delivery", "order": "O001"}]}

result = simulator.score(sc, plan)        # same structure as the API's Score response
result["score"]                           # unrounded; API rounds to 2 decimals
result["validation"]["violations"]        # must be empty before submitting
result["metrics"]["trucks"][0]["schedule"]  # arrival / wait / late / departure per stop

simulator.api_round(result)               # rounded exactly like the API returns it
```

Cities are referred to by integer index internally (`sc.city_ids[i]` gives the ID,
`sc.city_index["C001"]` the index).

**Plugging in another data source** (e.g. the data-layer database): build the same raw
lists/dicts the API returns and call
`loader.from_raw(scenario_id, cities, trucks, orders, distance_matrix)`. Everything else
works unchanged. The data must be the same version the server is running (the server
regenerates all scenarios on restart).

## Command line

```powershell
python -m gruber.cli local scenario_small plan.json     # local score, no API call
python -m gruber.cli validate scenario_small plan.json  # API Validate (free) vs local check
```

## API safety rules

- GET `/Scenarios...` and Validate are free and unlimited.
- `Client.simulate()` / `Client.score()` print what they will send and ask **y/n** before
  sending (or need an `Approval` from `api.confirm_batch()` for a batch).
- **`scenario_competitive` allows only 3 Simulate and 3 Score calls per team in total.**
  The client refuses both unless `i_am_sure=True` (`--i-am-sure` on the command line).
- Every Validate / Simulate / Score request and response is logged to
  `data/api_responses/` (git-ignored).

## Behaviour worth knowing when building a solver

Full details in [`docs/semantics.md`](../docs/semantics.md). The main points:

- Every violation costs 20 points. Plans must have zero violations.
- An order needing a special truck type, carried by the wrong type, is still loaded and driven
  but never counts as fulfilled, and it adds a violation at **every** stop until loaded.
- Driving time per leg = `ceil(km * 60 / 70)` minutes; 30 min service per stop.
- Breaks: 45 min after 4.5 h driving, 11 h rest after 9 h driving. Time spent standing
  (service, waiting) right before counts toward the pause, so often only part of it is added.
- Arriving early at a window means waiting until `from`. Up to 60 min late keeps 100 % → 50 %
  of the order's value; more than 60 min late means not fulfilled. If an order is late at
  both stops, the larger lateness counts.
- Score = 10 × (0.50 fulfillment + 0.20 cost efficiency + 0.15 loaded ratio + 0.15 CO₂
  efficiency) − 20 × violations. Reference cost/CO₂ use the direct pickup→delivery
  distances of all orders × fraction fulfilled × the cheapest/cleanest truck in the fleet.

## Testing

```powershell
python -m pytest -q tests                 # unit tests + the 156 saved API parity cases
python -m tools.parity compare            # saved API responses vs local simulator
python -m tools.validate_fuzz 20          # random plans vs API Validate (free)
```

After a server restart (new data): `cd database && ./run_all.sh`, then `python -m tools.parity build`, and
re-run parity with `python -m tools.parity send <scenario>` (asks y/n, uses Simulate/Score
calls; never on competitive).
