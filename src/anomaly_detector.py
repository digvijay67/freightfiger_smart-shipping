"""Own-history and peer baselines plus configurable increase detection."""
from collections import defaultdict
from decimal import Decimal


def enrich_with_baselines(weekly: list[dict[str, object]], history_weeks: int = 8) -> list[dict[str, object]]:
    by_route: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    by_week_type: dict[tuple[object, str], list[dict[str, object]]] = defaultdict(list)
    for item in weekly:
        by_route[(item["origin"], item["destination"], item["route_type"])].append(item)
        by_week_type[(item["week"], item["route_type"])].append(item)
    for rows in by_route.values():
        rows.sort(key=lambda r: r["week"])
    output = []
    for row in weekly:
        route_rows = by_route[(row["origin"], row["destination"], row["route_type"])]
        earlier = [item["rate"] for item in route_rows if item["week"] < row["week"]]
        prior = earlier[-history_weeks:]
        peers = [item["rate"] for item in by_week_type[(row["week"], row["route_type"])]
                 if (item["origin"], item["destination"], item["route_type"])
                 != (row["origin"], row["destination"], row["route_type"])]
        enriched = dict(row)
        enriched["own_baseline"] = sum(prior, Decimal(0)) / len(prior) if prior else None
        enriched["own_weeks"] = len(prior)
        enriched["peer_baseline"] = sum(peers, Decimal(0)) / len(peers) if peers else None
        enriched["peer_routes"] = len(peers)
        output.append(enriched)
    return output


def is_increase_anomaly(row: dict[str, object], threshold_pct: Decimal) -> bool:
    """Flag when the rate exceeds threshold against either available baseline."""
    rate = row["rate"]
    # A percentage increase from zero is undefined; output rendering treats it
    # as unavailable too, so do not flag against a zero baseline here.
    baselines = [row[key] for key in ("own_baseline", "peer_baseline")
                 if row[key] is not None and row[key] > 0]
    return any(rate > baseline * (Decimal(1) + threshold_pct / Decimal(100)) for baseline in baselines)
