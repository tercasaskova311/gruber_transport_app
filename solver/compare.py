"""
compare.py — step 6: initial (greedy) plan vs optimized (ALNS) plan, in plain words.
"""
from __future__ import annotations

from evaluator import score, simulate_truck
from instance import Instance
from solver import Solution, best_insertion


def summarize(inst: Instance, sol: Solution) -> dict:
    S, comp = score(inst, sol.tot)
    t = sol.tot
    used = [k for k in range(len(inst.trucks)) if sol.routes[k]]
    late = {oi: m for k in used for oi, m in sol.res[k].late.items()}
    util_num = sum(sol.res[k].load_km for k in used)
    util_den = sum(sol.res[k].km * inst.trucks[k].capacity for k in used)
    return {
        "score": round(S, 2),
        "fulfillment": round(comp["fulfillment"], 2),
        "cost_eff": round(comp["cost_eff"], 2),
        "loaded_ratio": round(comp["loaded_ratio"], 2),
        "co2_eff": round(comp["co2_eff"], 2),
        "orders_delivered": t.n_fulfilled,
        "orders_total": inst.n_orders,
        "value_delivered": round(t.value, 2),
        "value_total": round(inst.value_total, 2),
        "total_km": round(t.km, 1),
        "empty_km": round(t.km - t.loaded_km, 1),
        "empty_pct": round(100 * (t.km - t.loaded_km) / t.km, 2) if t.km else 0.0,
        "cost_eur": round(t.cost, 2),
        "ref_cost_eur": round(comp["ref_cost"], 2),
        "co2_kg": round(t.co2, 2),
        "ref_co2_kg": round(comp["ref_co2"], 2),
        "trucks_used": len(used),
        "orders_late": len(late),
        "late_minutes": round(sum(late.values()), 1),
        "utilization_pct": round(100 * util_num / util_den, 2) if util_den else 0.0,
    }


def points_lost(summary: dict) -> dict:
    """Waterfall: 1000 → points lost on each goal → final score."""
    return {
        "deliveries": round(5.0 * (100 - summary["fulfillment"]), 2),
        "cost": round(2.0 * (100 - summary["cost_eff"]), 2),
        "empty_km": round(1.5 * (100 - summary["loaded_ratio"]), 2),
        "co2": round(1.5 * (100 - summary["co2_eff"]), 2),
    }


def why_missed(inst: Instance, sol: Solution) -> dict[str, str]:
    """One plain sentence per undelivered order: which constraint is binding."""
    out = {}
    for oi in sorted(sol.unassigned):
        o = inst.orders[oi]
        if not inst.compatible[oi]:
            out[o.id] = (f"No truck can carry it ({o.weight:.0f} kg"
                         + (f", needs {o.required_type}" if o.required_type else "") + ").")
            continue
        alone_ok = any(simulate_truck(inst, k, [(True, oi), (False, oi)]).feasible for k in inst.compatible[oi])
        if not alone_ok:
            out[o.id] = "Its time window can't be met by any compatible truck, even driving only this order."
            continue
        ins = [best_insertion(inst, sol, oi, k, topk=50) for k in inst.compatible[oi]]
        ins = [x for x in ins if x is not None]
        if not ins:
            out[o.id] = ("Every compatible truck is already busy: adding it would break capacity "
                         "or make another delivery more than 60 min late.")
        else:
            b = max(ins, key=lambda x: x.dS)
            out[o.id] = (f"Feasible on {inst.trucks[b.k].id}, but it would lower the score by "
                         f"{-b.dS:.2f} points (detour cost > its value).")
    return out


METRICS = [
    ("score", "Score (of 1000)", True),
    ("fulfillment", "Fulfillment (0-100)", True),
    ("cost_eff", "Cost efficiency (0-100)", True),
    ("loaded_ratio", "Loaded ratio (0-100)", True),
    ("co2_eff", "CO₂ efficiency (0-100)", True),
    ("orders_delivered", "Orders delivered", True),
    ("total_km", "Total km", False),
    ("empty_km", "Empty km", False),
    ("cost_eur", "Cost (€)", False),
    ("co2_kg", "CO₂ (kg)", False),
    ("trucks_used", "Trucks used", None),
    ("orders_late", "Orders late (≤60 min)", False),
    ("utilization_pct", "Truck utilization (%)", True),
]


def compare(inst: Instance, before: Solution, after: Solution) -> tuple[dict, str]:
    b, a = summarize(inst, before), summarize(inst, after)
    rows = ["| Metric | Initial (greedy ΔS) | Optimized (ALNS) | Change |", "|---|---:|---:|---:|"]
    for key, label, higher_better in METRICS:
        d = a[key] - b[key]
        mark = ""
        if higher_better is not None and abs(d) > 1e-9:
            mark = " ✅" if (d > 0) == higher_better else " ⚠️"
        rows.append(f"| {label} | {b[key]:,} | {a[key]:,} | {d:+,.2f}{mark} |")

    lb, la = points_lost(b), points_lost(a)
    wf = ["| Points lost on… | Initial | Optimized |", "|---|---:|---:|"]
    for k in lb:
        wf.append(f"| {k} | {lb[k]} | {la[k]} |")

    headline = (f"ALNS moved the score from **{b['score']:.1f} to {a['score']:.1f}** "
                f"({a['score'] - b['score']:+.1f} points): "
                f"{a['total_km'] - b['total_km']:+,.0f} km, {a['empty_km'] - b['empty_km']:+,.0f} empty km, "
                f"€{a['cost_eur'] - b['cost_eur']:+,.0f}, {a['co2_kg'] - b['co2_kg']:+,.0f} kg CO₂, "
                f"{a['orders_delivered'] - b['orders_delivered']:+d} orders delivered.")

    missed = why_missed(inst, after)
    miss_md = "\n".join(f"- **{k}**: {v}" for k, v in missed.items()) or "- None: every order is delivered."

    md = "\n\n".join([
        "# Initial vs optimized plan", headline, "\n".join(rows),
        "## Where the points go (waterfall: 1000 − losses = score)", "\n".join(wf),
        "## Orders not delivered, and why", miss_md,
    ])
    return {"before": b, "after": a, "points_lost_before": lb, "points_lost_after": la,
            "missed_reasons": missed, "headline": headline}, md
