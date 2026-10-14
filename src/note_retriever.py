"""Conservative deterministic note retrieval and applicability checks."""
import re
from datetime import date, timedelta

ROUTE_SEP = re.compile(r"\s*[-\u2013\u2014]\s*")
POSITIVE = re.compile(r"\b(surcharge|higher (?:trip )?costs?|pushing up transportation costs?|costs? rose|increased? costs?)\b", re.I)
NEGATIVE = re.compile(
    r"not significantly affected|not part of this dataset|stable|no major disruptions|"
    r"no significant disruptions|normal conditions|without a rate change|no rate change|"
    r"improved road conditions|did not (?:increase|raise|push up)|no surcharge|"
    r"costs? (?:were|are|was|is)?\s*(?:unaffected|not affected|not impacted|did not rise|remained unchanged|decreased|fell)|"
    r"rates? (?:remained unchanged|did not change)",
    re.I,
)


def _norm_route(text: str) -> str:
    return "-".join(part.strip().casefold() for part in ROUTE_SEP.split(text.strip()))


def _validity(note: dict[str, str]) -> tuple[date, date]:
    start = date.fromisoformat(note["date"])
    body = note["note"]
    # The flooding note states its end date explicitly. Its start is the note date.
    span = re.search(r"from\s+([A-Za-z]+)\s+(\d{1,2})\s+to\s+([A-Za-z]+)\s+(\d{1,2})", body, re.I)
    if span:
        month_names = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
        months = {alias: number for number, name in enumerate(month_names, 1)
                  for alias in (name.casefold(), name[:3].casefold())}
        end_month = months[span.group(3).casefold()]
        end_year = start.year + (1 if end_month < start.month else 0)
        return start, date(end_year, end_month, int(span.group(4)))
    # Otherwise a dated note applies only to its Monday-based week.
    monday = start - timedelta(days=start.weekday())
    return monday, monday + timedelta(days=6)


def retrieve_notes(route: str, week: date, notes: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return notes whose explicit route, time window, and text support a rise."""
    if week.weekday() != 0:
        raise ValueError("week must be a Monday date")
    matches = []
    route_key = _norm_route(route)
    for note in notes:
        applies = note["applies_to"].strip()
        if applies.casefold() != "all routes" and _norm_route(applies) != route_key:
            continue
        start, end = _validity(note)
        # Week overlaps a note's validity window.
        if week > end or week + timedelta(days=6) < start:
            continue
        if NEGATIVE.search(note["note"]) or not POSITIVE.search(note["note"]):
            continue
        matches.append(note)
    return sorted(matches, key=lambda n: (n["date"], n["note_id"]))
