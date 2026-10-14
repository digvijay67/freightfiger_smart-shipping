"""Deterministic weekly cost-per-tonne-kilometre aggregation."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def parse_decimal(value: str, field: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"Invalid numeric value for {field}: {value!r}") from None
    if not result.is_finite():
        raise ValueError(f"Non-finite numeric value for {field}: {value!r}")
    return result


def monday_of(value: str) -> date:
    parsed = date.fromisoformat(value)
    return parsed - timedelta(days=parsed.weekday())


def calculate_weekly_rates(records: list[dict[str, str]]) -> list[dict[str, object]]:
    """Aggregate each origin/destination/type/Monday week using exact decimals."""
    totals: dict[tuple[str, str, str, date], list[Decimal]] = defaultdict(
        lambda: [Decimal(0), Decimal(0)]
    )
    for row in records:
        quantity = parse_decimal(row["quantity_tonnes"], "quantity_tonnes")
        distance = parse_decimal(row["distance_km"], "distance_km")
        freight = parse_decimal(row["freight_cost_inr"], "freight_cost_inr")
        if quantity <= 0 or distance <= 0 or freight < 0:
            raise ValueError(f"Non-positive quantity/distance or negative cost in shipment {row.get('shipment_id')}")
        key = (row["origin"], row["destination"], row["route_type"], monday_of(row["shipment_date"]))
        totals[key][0] += freight
        totals[key][1] += quantity * distance
    weekly = []
    for (origin, destination, route_type, week), (freight_sum, tonne_km_sum) in totals.items():
        weekly.append({
            "origin": origin, "destination": destination, "route_type": route_type,
            "route": f"{origin}-{destination}", "week": week,
            "rate": freight_sum / tonne_km_sum,
        })
    return sorted(weekly, key=lambda r: (r["week"], r["route_type"], r["route"]))
