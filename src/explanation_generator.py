"""Format evidence-limited report rows; notes cannot alter numeric flags."""
from decimal import Decimal, ROUND_HALF_UP
from src.note_retriever import retrieve_notes


def _pct(rate: Decimal, baseline: Decimal | None, label: str) -> str:
    if baseline is None or baseline == 0:
        return f"N/A vs {label} (baseline unavailable)"
    value = ((rate - baseline) / baseline * Decimal(100)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return f"{value:+.1f}% vs {label}"


def build_output_row(
    row: dict[str, object],
    notes: list[dict[str, str]],
    rag_service=None,
) -> dict[str, str]:
    route = str(row["route"])
    week = row["week"]
    rate = row["rate"]
    own = row["own_baseline"]
    peer = row["peer_baseline"]
    applicable = retrieve_notes(route, week, notes)
    note = applicable[0] if applicable else None
    rag_result = rag_service.explain(route, week, applicable) if rag_service is not None else None
    if rag_result is not None:
        note = next((candidate for candidate in applicable
                     if candidate["note_id"] == rag_result["note_id"]), None)
        # The service validates IDs against the eligible evidence; keep a final
        # guard here because this function owns the CSV value being written.
        if note is None:
            rag_service._diagnostic(
                "fallback_unrecognized_note_id",
                f"returned note ID was not eligible for {route} {week}",
                warning=True,
            )
            note = applicable[0] if applicable else None
    if note:
        flag = "No (justified)"
        matched_id = note["note_id"]
        if rag_result is not None and rag_result["note_id"] == matched_id:
            reason = (
                f"Matches note {matched_id} dated {note['date']}: "
                f"{rag_result['explanation']} Evidence quote: {rag_result['evidence_quote']}"
            )
        else:
            reason = f"Matches note {matched_id} dated {note['date']}: {note['note']}"
    else:
        flag = "Yes"
        matched_id = ""
        reason = "No applicable note supports this increase for the route and week; increase is unexplained and worth a human review."
    return {
        "route": route,
        "week_of": week.isoformat(),
        "cost_per_tonne_km": f"{rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}",
        "vs_own_history": _pct(rate, own, "this route's past average"),
        "vs_similar_routes": _pct(rate, peer, "similar route types this week"),
        "flagged": flag,
        "matched_note_id": matched_id,
        "reason": reason,
    }
