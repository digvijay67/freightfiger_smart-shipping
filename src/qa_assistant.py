"""Deterministic, results-grounded terminal Q&A for the shipping report."""
import csv
import calendar
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable

from src.anomaly_detector import enrich_with_baselines, is_increase_anomaly
from src.config import (
    ANOMALY_THRESHOLD_PCT,
    NOTES_FILE,
    OUTPUT_COLUMNS,
    REPORT_FILE,
    REPRODUCIBILITY_FILE,
    SAMPLE_OUTPUT_FILE,
    SHIPMENTS_FILE,
)
from src.cost_calculator import calculate_weekly_rates
from src.data_loader import load_csv
from src.explanation_generator import build_output_row
from src.report_writer import sha256_file
from src.main import (
    NOTE_COLUMNS,
    SHIPMENT_COLUMNS,
    _validate_source_records,
    parse_threshold,
    validate_output,
)
from src.note_retriever import retrieve_notes
from src.local_rag import LocalRagNotes


class StaleResultsError(RuntimeError):
    """Raised when the report or its source snapshot is stale or unverifiable."""


def _read_sample_columns(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return next(csv.reader(stream))


def _recorded_run(evidence_path: Path) -> tuple[tuple[str, str], Decimal]:
    if not evidence_path.is_file():
        raise StaleResultsError("No reproducibility evidence found. Run `python -m src.main` first.")
    evidence = evidence_path.read_text(encoding="utf-8")
    shipment = re.search(
        r"shipment_records\.csv SHA-256 before/after: ([0-9a-f]{64}) / ([0-9a-f]{64})", evidence
    )
    notes = re.search(
        r"context_notes\.csv SHA-256 before/after: ([0-9a-f]{64}) / ([0-9a-f]{64})", evidence
    )
    threshold_match = re.search(r"^Threshold: ([^%\r\n]+)%", evidence, re.MULTILINE)
    if not shipment or not notes or not threshold_match:
        raise StaleResultsError("Reproducibility evidence is incomplete. Run `python -m src.main` first.")
    if shipment.group(1) != shipment.group(2) or notes.group(1) != notes.group(2):
        raise StaleResultsError("The recorded run did not use stable inputs. Run `python -m src.main` again.")
    return (shipment.group(1), notes.group(1)), parse_threshold(threshold_match.group(1))


def _current_hashes(shipments_path: Path, notes_path: Path) -> tuple[str, str]:
    return sha256_file(shipments_path), sha256_file(notes_path)


def _report_matches_calculation(
    actual_rows: list[dict[str, str]],
    expected_rows: list[dict[str, str]],
    notes: list[dict[str, str]],
) -> bool:
    """Validate deterministic report fields and allow only evidence-backed RAG prose."""
    if len(actual_rows) != len(expected_rows):
        return False
    deterministic_columns = [column for column in OUTPUT_COLUMNS if column not in {"reason", "matched_note_id"}]
    notes_by_id = {note["note_id"]: note for note in notes}
    for actual, expected in zip(actual_rows, expected_rows):
        if any(actual[column] != expected[column] for column in deterministic_columns):
            return False
        if not expected["matched_note_id"]:
            if actual["matched_note_id"] or actual["reason"] != expected["reason"]:
                return False
            continue
        note_id = actual["matched_note_id"]
        note = notes_by_id.get(note_id)
        week = date.fromisoformat(actual["week_of"])
        if note is None or note_id not in {
            item["note_id"] for item in retrieve_notes(actual["route"], week, notes)
        }:
            return False
        prefix = f"Matches note {note_id} dated {note['date']}:"
        if not actual["reason"].startswith(prefix):
            return False
        if actual["reason"] == expected["reason"]:
            continue
        marker = "Evidence quote: "
        if marker not in actual["reason"]:
            return False
        explanation, quote = actual["reason"][len(prefix):].split(marker, 1)
        try:
            LocalRagNotes._validate_generated(
                {"note_id": note_id, "explanation": explanation, "evidence_quote": quote.strip()},
                [note],
            )
        except ValueError:
            return False
    return True


class QAAssistant:
    """Answers supported questions using a verified report and its source data."""

    def __init__(
        self,
        report_rows: list[dict[str, str]],
        detail_rows: list[dict[str, object]],
        notes: list[dict[str, str]],
        input_hashes: tuple[str, str],
        hash_reader: Callable[[], tuple[str, str]],
    ) -> None:
        self.rows = report_rows
        self.details = detail_rows
        self.notes = {note["note_id"]: note for note in notes}
        self.input_hashes = input_hashes
        self.hash_reader = hash_reader
        self.last_route: str | None = None
        self._details_by_key = {
            (str(row["route"]), row["week"].isoformat()): row for row in detail_rows
        }

    @classmethod
    def load_current(
        cls,
        threshold_text: str = ANOMALY_THRESHOLD_PCT,
        *,
        shipments_path: Path = SHIPMENTS_FILE,
        notes_path: Path = NOTES_FILE,
        report_path: Path = REPORT_FILE,
        evidence_path: Path = REPRODUCIBILITY_FILE,
        sample_path: Path = SAMPLE_OUTPUT_FILE,
    ) -> "QAAssistant":
        """Load only when report, threshold, evidence, and current input hashes agree."""
        threshold = parse_threshold(threshold_text)
        recorded_hashes, recorded_threshold = _recorded_run(evidence_path)
        if recorded_threshold != threshold:
            raise StaleResultsError(
                "The report used a different threshold. Run `python -m src.main` with the configured threshold first."
            )
        current_hashes = _current_hashes(shipments_path, notes_path)
        if current_hashes != recorded_hashes:
            raise StaleResultsError(
                "Shipment data or context notes changed after the report was generated. "
                "Run `python -m src.main` before asking questions."
            )

        columns = _read_sample_columns(sample_path)
        if columns != OUTPUT_COLUMNS:
            raise StaleResultsError("The sample output schema differs from the configured report schema.")
        try:
            report_rows = load_csv(report_path, set(columns), expected_columns=columns)
            validate_output(report_rows, columns)
        except (OSError, ValueError) as error:
            raise StaleResultsError(
                "The saved report is missing or invalid. Run `python -m src.main` before asking questions."
            ) from error

        shipments = load_csv(
            shipments_path,
            set(SHIPMENT_COLUMNS),
            expected_columns=SHIPMENT_COLUMNS,
            nonempty_columns=set(SHIPMENT_COLUMNS),
        )
        notes = load_csv(
            notes_path,
            set(NOTE_COLUMNS),
            expected_columns=NOTE_COLUMNS,
            nonempty_columns=set(NOTE_COLUMNS),
        )
        _validate_source_records(shipments, notes)
        weekly = calculate_weekly_rates(shipments)
        enriched = enrich_with_baselines(weekly)
        expected_rows = [
            build_output_row(row, notes)
            for row in enriched
            if is_increase_anomaly(row, threshold)
        ]
        if not _report_matches_calculation(report_rows, expected_rows, notes):
            raise StaleResultsError(
                "The report's calculations or evidence references do not match current inputs. "
                "Run `python -m src.main` before asking questions."
            )
        return cls(report_rows, enriched, notes, current_hashes, lambda: _current_hashes(shipments_path, notes_path))

    def _check_fresh(self) -> None:
        if self.hash_reader() != self.input_hashes:
            raise StaleResultsError(
                "An input CSV changed during this chat. Answers stopped; rerun `python -m src.main` "
                "and restart the assistant."
            )

    @staticmethod
    def _normal(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold().replace("–", "-").replace("—", "-")).strip()

    def _routes_in(self, question: str) -> list[str]:
        normalized = self._normal(question)
        routes = sorted({str(row["route"]) for row in self.details}, key=lambda route: (-len(route), route.casefold()))
        return [route for route in routes if self._normal(route) in normalized]

    @staticmethod
    def _refers_to_previous_route(question: str) -> bool:
        return bool(re.search(r"\b(this|that|it)\s+route\b", question, re.I))

    def _week_in(self, question: str) -> date | None:
        match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", question)
        if not match:
            return None
        try:
            mentioned = date.fromisoformat(match.group(1))
        except ValueError:
            return None
        return mentioned - timedelta(days=mentioned.weekday())

    @staticmethod
    def _month_in(question: str) -> tuple[int, int, str] | None:
        month_names = {
            name.casefold(): index
            for index, name in enumerate(calendar.month_name)
            if name
        }
        month_names.update({
            name.casefold(): index
            for index, name in enumerate(calendar.month_abbr)
            if name
        })
        names = "|".join(sorted((re.escape(name) for name in month_names), key=len, reverse=True))
        match = re.search(rf"\b({names})\.?\s+(20\d{{2}})\b", question, re.I)
        if not match:
            return None
        month = month_names[match.group(1).rstrip(".").casefold()]
        year = int(match.group(2))
        return year, month, f"{calendar.month_name[month]} {year}"

    def _unknown_route_period_response(self, question: str) -> str | None:
        route = self._unknown_route_pair(question)
        if route is None:
            return None
        week = self._week_in(question)
        if week is not None:
            period = f"the week of {week.isoformat()}"
        else:
            month = self._month_in(question)
            if month is None:
                return None
            period = month[2]
        return (
            f"No data found for the {route} route in {period}. "
            "I cannot verify that it was flagged."
        )

    def _select(self, question: str) -> tuple[list[dict[str, str]], bool]:
        routes = self._routes_in(question)
        ambiguous = len(routes) > 1
        route = routes[0] if len(routes) == 1 else None
        if route:
            self.last_route = route
        elif self._refers_to_previous_route(question) and self.last_route:
            route = self.last_route
        selected = [row for row in self.rows if route is None or row["route"] == route]
        week = self._week_in(question)
        if week:
            selected = [row for row in selected if date.fromisoformat(row["week_of"]) == week]
        else:
            month = self._month_in(question)
            if month:
                year, month_number, _ = month
                selected = [
                    row for row in selected
                    if (date.fromisoformat(row["week_of"]).year,
                        date.fromisoformat(row["week_of"]).month) == (year, month_number)
                ]
        return selected, ambiguous

    @staticmethod
    def _rate(value: Decimal | None) -> str:
        return "unavailable" if value is None else f"{value:.4f} INR/tonne-km"

    @staticmethod
    def _increase(row: dict[str, object]) -> tuple[Decimal, str] | None:
        rate = row["rate"]
        candidates = []
        for key, label in (("own_baseline", "own history"), ("peer_baseline", "same-week peers")):
            baseline = row[key]
            if baseline is not None and baseline > 0:
                candidates.append(((rate - baseline) / baseline * Decimal(100), label))
        return max(candidates, key=lambda item: item[0]) if candidates else None

    def _largest_for_baseline(
        self, rows: list[dict[str, str]], baseline_key: str
    ) -> tuple[Decimal, dict[str, str]] | None:
        scored = []
        for report in rows:
            detail = self._details_by_key[(report["route"], report["week_of"])]
            baseline = detail[baseline_key]
            if baseline is None or baseline <= 0:
                continue
            increase = (detail["rate"] - baseline) / baseline * Decimal(100)
            if increase > 0:
                scored.append((increase, report))
        return max(scored, key=lambda item: (item[0], item[1]["week_of"], item[1]["route"])) if scored else None

    def _unknown_route_pair(self, question: str) -> str | None:
        known = {self._normal(str(row["route"])) for row in self.details}
        non_route_pairs = {
            "cost-per", "own-history", "same-week", "tonne-km", "route-type",
            "week-to-week", "month-to-month", "year-over-year",
        }
        for match in re.finditer(r"\b([A-Za-z]+)\s*[-\u2013\u2014]\s*([A-Za-z]+)\b", question):
            pair = self._normal(f"{match.group(1)}-{match.group(2)}")
            if pair not in known and pair not in non_route_pairs:
                return f"{match.group(1)}-{match.group(2)}"
        return None

    def _largest_increase_line(
        self, rows: list[dict[str, str]], baseline_key: str, baseline_label: str
    ) -> str | None:
        largest = self._largest_for_baseline(rows, baseline_key)
        if largest is None:
            return None
        pct, row = largest
        displayed_pct = pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return (
            f"Largest increase versus {baseline_label} baseline in the selected results: "
            f"{row['route']} in week {row['week_of']}, {row['cost_per_tonne_km']} INR/tonne-km, "
            f"up {displayed_pct:.1f}%."
        )

    def _describe(self, report: dict[str, str]) -> str:
        key = (report["route"], report["week_of"])
        detail = self._details_by_key[key]
        status = "unexplained (no supporting note)" if report["flagged"] == "Yes" else "justified by a matched context note"
        result = (
            f"{report['route']} for week {report['week_of']}: "
            f"{report['cost_per_tonne_km']} INR/tonne-km; "
            f"own history {report['vs_own_history']}; peers {report['vs_similar_routes']}; {status}."
        )
        note_id = report["matched_note_id"]
        if note_id and note_id in self.notes:
            note = self.notes[note_id]
            result += f" Evidence: note {note_id} ({note['date']}, {note['applies_to']}): {note['note']}"
            result += " This is supporting context, not proof of causation."
        return result

    def _explain_note_request(
        self, report: dict[str, str], *, causal_claim: bool = False, festival_claim: bool = False
    ) -> str:
        """Answer a route-week note question from the exact report row and cited note."""
        changes = []
        for column, label in (
            ("vs_own_history", "its historical baseline"),
            ("vs_similar_routes", "peer routes"),
        ):
            match = re.search(r"([+-]?\d+(?:\.\d+)?%)", report[column])
            if match:
                changes.append(f"{match.group(1).lstrip('+')} versus {label}")
        summary = (
            f"{report['route']} was flagged for the week of {report['week_of']}, "
            f"with a cost of {report['cost_per_tonne_km']} INR/tonne-km."
        )
        if changes:
            summary += " It increased by " + " and ".join(changes) + "."

        note_id = report["matched_note_id"]
        note = self.notes.get(note_id) if note_id else None
        if report["flagged"] == "Yes" or note is None:
            if causal_claim:
                claimed_cause = "a festival" if festival_claim else "the claimed cause"
                return (
                    summary + f" No eligible context note proves that {claimed_cause} caused this anomaly, "
                    "so the cause remains unexplained."
                )
            return (
                summary + " No eligible context note supports this anomaly, "
                "so the cause remains unexplained."
            )
        return (
            summary + f" Eligible context note {note_id} states: {note['note']} "
            "This is supporting context, not proof of causation."
        )

    def _causality_response(self, question: str, selected: list[dict[str, str]]) -> str:
        """Assess a causal premise against the exact anomaly and eligible notes."""
        routes = self._routes_in(question)
        week = self._week_in(question)
        if not routes:
            return "Please name the route you want checked for causal evidence."
        if week is None:
            return "Please include an ISO date or week so I can check the exact anomaly and note dates."
        if not selected:
            return f"No matching anomaly was found for {routes[0]} for the week of {week.isoformat()}."

        route = routes[0]
        eligible = retrieve_notes(route, week, list(self.notes.values()))
        requested_ids = re.findall(r"\bN\d+\b", question, re.I)
        if requested_ids:
            named_eligible = [note for note in eligible if note["note_id"].casefold() in {
                note_id.casefold() for note_id in requested_ids
            }]
            if not named_eligible:
                note_list = ", ".join(requested_ids)
                return (
                    f"{note_list} is not eligible for {route} for the week of {week.isoformat()}, "
                    "so it cannot support or prove the cause. The cause remains unverified."
                )
            eligible = named_eligible

        if not eligible:
            return (
                f"No eligible context note supports a causal conclusion for {route} for the week of "
                f"{week.isoformat()}; the cause remains unexplained."
            )

        report = selected[0]
        preferred_id = report["matched_note_id"]
        matched = next((note for note in eligible if note["note_id"] == preferred_id), eligible[0])
        context_subject = "flooding" if re.search(r"\bflood", matched["note"], re.I) else "the event described in the note"
        return (
            f"{route} was flagged for the week of {week.isoformat()} at "
            f"{report['cost_per_tonne_km']} INR/tonne-km. Note {matched['note_id']} "
            f"({matched['date']}) states: {matched['note']} This supports {context_subject} as relevant context "
            f"for the route and week, but it does not prove {context_subject} caused the anomaly."
        )

    def _examples(self) -> list[dict[str, str]]:
        ranked = []
        for report in self.rows:
            detail = self._details_by_key[(report["route"], report["week_of"])]
            increase = self._increase(detail)
            score = increase[0] if increase else Decimal("-Infinity")
            ranked.append((score, report))
        ranked.sort(key=lambda item: (-item[0], item[1]["week_of"], item[1]["route"]))
        chosen: list[dict[str, str]] = []
        used_routes: set[str] = set()
        # Include a note-supported row when available, then favor distinct routes.
        supported = [item for item in ranked if item[1]["matched_note_id"]]
        unexplained = [item for item in ranked if not item[1]["matched_note_id"]]
        for pool in (supported, unexplained, ranked):
            for _, row in pool:
                if row["route"] not in used_routes:
                    chosen.append(row)
                    used_routes.add(row["route"])
                    if len(chosen) == 3:
                        return chosen
        for _, row in ranked:
            if row not in chosen:
                chosen.append(row)
                if len(chosen) == 3:
                    break
        return chosen

    def answer(self, question: str) -> str:
        self._check_fresh()
        question = question.strip()
        if not question:
            return "Please enter a question about the computed shipping results."
        q = question.casefold()

        # "Last" refers to the final anomaly row in the current report's order.
        # Resolve this before general summary routing so a specific request can
        # never fall through to the overall report summary.
        if re.search(r"\blast\s+(?:detected\s+)?anomal(?:y|ies)\b", q):
            if not self.rows:
                return "There are no detected anomaly rows in the current report."
            return self._describe(self.rows[-1])

        selected, ambiguous = self._select(question)
        if ambiguous:
            return "Your question names multiple routes. Ask about one route at a time or ask for all routes."

        unknown_route_period = self._unknown_route_period_response(question)
        if unknown_route_period:
            return unknown_route_period

        asks_causal_certainty = bool(re.search(
            r"\bcan\s+(?:we|i)\s+(?:still\s+)?(?:conclude|infer|say|be certain|be sure)\b|"
            r"\b(?:does|do|did)\s+(?:this|that|it|the note|the evidence)?\s*(?:prove|establish|confirm)\b|"
            r"\b(?:was|were|is|are|has been|have been)\s+(?:it|they|this|that|the anomaly)?\s*caused by\b|"
            r"\bcan\s+(?:we|i)\s+be certain\b",
            q,
        ))
        if asks_causal_certainty:
            return self._causality_response(question, selected)

        asks_explanatory_note = bool(re.search(
            r"\b(?:which|what)\s+(?:context\s+)?notes?\b.*\b(?:explain|explains|support|supports|justify|justifies)\b",
            q,
        ))
        note_question = bool(re.search(r"\b(?:which|what)\s+(?:context\s+)?notes?\b", q))
        causal_claim = bool(re.search(r"\b(cause|caused|causing|prove|proves|proof|festival)\b", q))
        asks_explanatory_note = asks_explanatory_note or (note_question and causal_claim)
        if asks_explanatory_note:
            mentioned_routes = self._routes_in(question)
            if not mentioned_routes:
                return "Please name the route and week you want checked."
            week = self._week_in(question)
            if week is None and self._month_in(question) is None:
                return "Please include an ISO date or week so I can check the exact anomaly."
            if not selected:
                route = mentioned_routes[0]
                period = f"week of {week.isoformat()}" if week else self._month_in(question)[2]
                return f"No matching anomaly was found for {route} for the {period}."
            festival_claim = bool(re.search(r"\bfestival\b", q))
            return "\n".join(
                self._explain_note_request(
                    row, causal_claim=causal_claim, festival_claim=festival_claim
                )
                for row in selected
            )

        if re.search(r"\b(three|3)\b", q) and re.search(r"anomal|example|representative", q):
            examples = self._examples()
            if not examples:
                return "There are no detected anomaly rows to demonstrate."
            return "Three representative examples selected from the current results:\n" + "\n".join(
                f"{index}. {self._describe(row)}" for index, row in enumerate(examples[:3], 1)
            )

        if re.search(r"\b(largest|highest|biggest)\b", q) and re.search(r"increase|rise|pricier|cost", q):
            unknown_route = self._unknown_route_pair(question)
            if unknown_route:
                return f"I couldn't find route {unknown_route} in the current shipment data."
            asks_history = bool(re.search(r"\b(history|historical|own[- ]history|past average)\b", q))
            asks_peers = bool(re.search(r"\b(peer|peers|similar routes?|route types?)\b", q))
            baselines = []
            if asks_history and not asks_peers:
                baselines = [("own_baseline", "historical (own-history)")]
            elif asks_peers and not asks_history:
                baselines = [("peer_baseline", "same-week peer")]
            else:
                baselines = [
                    ("own_baseline", "historical (own-history)"),
                    ("peer_baseline", "same-week peer"),
                ]
            lines = [
                line for key, label in baselines
                if (line := self._largest_increase_line(selected, key, label)) is not None
            ]
            if not lines:
                return "No available positive baseline supports ranking an increase in the selected results."
            return "\n".join(lines) + " The comparison does not establish a cause."

        detail_request = bool(re.search(
            r"\b(tell me more|more about|explain|what happened|show details|details for|why|reason)\b",
            q,
        ))
        if detail_request:
            mentioned_routes = self._routes_in(question)
            has_route_pair = bool(re.search(r"\b[A-Za-z][A-Za-z .']*\s*[-\u2013\u2014]\s*[A-Za-z][A-Za-z .']*\b", question))
            if not mentioned_routes and not (self._refers_to_previous_route(question) and self.last_route):
                # Preserve a clear no-match answer for an explicitly named but
                # unknown route/date pair, without borrowing an old route from
                # earlier conversation turns.
                if has_route_pair and self._week_in(question):
                    return "No anomaly row matches that route and week in the current report."
                return "Please name the route you want explained; I will not infer which one you mean."

            if not selected:
                return "No anomaly row matches that route and week in the current report."
            if self._week_in(question) is None and len(selected) > 1:
                route = mentioned_routes[0] if mentioned_routes else self.last_route
                return f"I found multiple anomalies for {route}. Please include an ISO date or week to choose one."
            return "\n".join(self._describe(row) for row in selected)

        if re.search(r"baseline|historical|peer", q):
            mentioned_routes = self._routes_in(question)
            if not mentioned_routes and not (self._refers_to_previous_route(question) and self.last_route):
                unknown_route = self._unknown_route_pair(question)
                if unknown_route:
                    return f"I couldn't find route {unknown_route} in the current shipment data."
                return (
                    "The own-history baseline is the arithmetic mean of up to eight most recent available weekly "
                    "rates for the same route and route_type, using only weeks strictly before the current week. "
                    "If fewer than eight prior rates exist, it uses all available rates without padding or extrapolation. "
                    "The peer baseline is the average cost per tonne-km in the same week across all other routes "
                    "with the same route_type, excluding the current route. An anomaly is flagged when either "
                    "available positive baseline is exceeded by the configured threshold."
                )
            route = mentioned_routes[0] if len(mentioned_routes) == 1 else self.last_route
            week = self._week_in(question)
            baseline_rows = [
                detail for detail in self.details
                if (route is None or detail["route"] == route)
                and (week is None or detail["week"] == week)
            ]
            if week is None:
                anomaly_keys = {
                    (row["route"], row["week_of"])
                    for row in self.rows
                    if route is None or row["route"] == route
                }
                baseline_rows = [
                    detail for detail in baseline_rows
                    if (detail["route"], detail["week"].isoformat()) in anomaly_keys
                ]
            if not baseline_rows:
                return "No anomaly row has calculated baselines for that route; include an ISO date to query another route-week."
            lines = []
            for detail in baseline_rows:
                lines.append(
                    f"{detail['route']} {detail['week']}: own-history baseline "
                    f"{self._rate(detail['own_baseline'])} from {detail['own_weeks']} prior available weeks; "
                    f"same-week peer baseline {self._rate(detail['peer_baseline'])} "
                    f"from {detail['peer_routes']} other route(s) of the same route type."
                )
            return "\n".join(lines)

        if re.search(r"support|evidence|context note|matched note|unexplained", q):
            wants_unsupported = bool(re.search(r"unexplained|unsupported|no supporting|without (?:a )?note|no evidence", q))
            target = [row for row in selected if (row["flagged"] == "Yes") == wants_unsupported]
            if not target:
                return "No matching anomalies of that evidence type appear in the current report."
            return "\n".join(self._describe(row) for row in target)

        if re.search(r"summari[sz]|non-technical|plain english|overall|findings", q):
            justified = sum(row["flagged"] == "No (justified)" for row in self.rows)
            unexplained = sum(row["flagged"] == "Yes" for row in self.rows)
            route_count = len({row["route"] for row in self.rows})
            return (
                f"The current report contains {len(self.rows)} unusual-cost route-weeks across {route_count} routes. "
                f"{justified} have a route/date-matched context note; {unexplained} have no supporting note and "
                "are marked for human review. A note is context, not proof that it caused the increase."
            )

        if re.search(r"anomal|unusual|flagged|which routes|list routes|how many|count", q):
            if not selected:
                return "No anomaly rows match that route or week in the current report."
            routes = sorted({row["route"] for row in selected})
            return (
                f"{len(selected)} anomaly row(s) across {len(routes)} route(s): " + ", ".join(routes) + ". "
                "Rows include both note-supported increases and unexplained increases."
            )

        return (
            "I could not map that to a supported question. Try asking for anomaly counts/routes, a specific route's "
            "explanation or baselines, note-supported/unexplained anomalies, three examples, the largest increase, "
            "or a plain-English summary."
        )


def interactive_chat(threshold_text: str = ANOMALY_THRESHOLD_PCT) -> None:
    """Run a multi-question terminal session, refusing stale results."""
    try:
        assistant = QAAssistant.load_current(threshold_text)
    except (OSError, ValueError, StaleResultsError) as error:
        print(f"Cannot start Q&A: {error}")
        return
    print("Shipping results Q&A. Ask about anomalies, routes, baselines, notes, or examples. Type 'exit' to quit.")
    while True:
        try:
            question = input("You> ").strip()
        except EOFError:
            print()
            return
        if question.casefold() in {"exit", "quit", "q"}:
            print("Goodbye.")
            return
        try:
            print("Assistant> " + assistant.answer(question))
        except StaleResultsError as error:
            print(f"Assistant> {error}")
            return
