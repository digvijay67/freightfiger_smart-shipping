"""Run a small, deterministic, manually labeled evaluation against source data."""
import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.anomaly_detector import enrich_with_baselines, is_increase_anomaly
from src.config import (ANOMALY_THRESHOLD_PCT, NOTES_FILE, OUTPUT_COLUMNS,
                        SAMPLE_OUTPUT_FILE, SHIPMENTS_FILE)
from src.cost_calculator import calculate_weekly_rates
from src.data_loader import load_csv
from src.explanation_generator import build_output_row
from src.main import (NOTE_COLUMNS, SHIPMENT_COLUMNS, _validate_source_records,
                      parse_threshold, validate_output)

EVALUATION_CASES_FILE = Path(__file__).resolve().parents[1] / "data" / "evaluation_cases.csv"
CASE_COLUMNS = ["case_id", "route", "week_of", "expected_anomaly", "expected_verdict",
                "expected_note_id", "source_note_ids_reviewed", "manual_basis"]
ALLOWED_VERDICTS = {"justified", "unexplained", "not_anomaly"}


def _load_cases() -> list[dict[str, str]]:
    return load_csv(EVALUATION_CASES_FILE, set(CASE_COLUMNS), expected_columns=CASE_COLUMNS,
                    nonempty_columns=set(CASE_COLUMNS) - {"expected_note_id"})


def _sample_header() -> list[str]:
    with SAMPLE_OUTPUT_FILE.open("r", encoding="utf-8-sig", newline="") as stream:
        return next(csv.reader(stream))


def evaluate_cases() -> tuple[list[dict[str, object]], Decimal]:
    """Return case results and the active configured threshold; never writes outputs."""
    threshold = parse_threshold(ANOMALY_THRESHOLD_PCT)
    if _sample_header() != OUTPUT_COLUMNS:
        raise ValueError("Sample output header differs from the production output contract")

    shipments = load_csv(SHIPMENTS_FILE, set(SHIPMENT_COLUMNS), expected_columns=SHIPMENT_COLUMNS,
                         nonempty_columns=set(SHIPMENT_COLUMNS))
    notes = load_csv(NOTES_FILE, set(NOTE_COLUMNS), expected_columns=NOTE_COLUMNS,
                     nonempty_columns=set(NOTE_COLUMNS))
    _validate_source_records(shipments, notes)
    weekly = enrich_with_baselines(calculate_weekly_rates(shipments))
    by_route_week: dict[tuple[str, date], list[dict[str, object]]] = {}
    for row in weekly:
        by_route_week.setdefault((str(row["route"]), row["week"]), []).append(row)

    cases = _load_cases()
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Evaluation case IDs must be unique")

    results: list[dict[str, object]] = []
    for case in cases:
        expected_anomaly_text = case["expected_anomaly"].strip().casefold()
        if expected_anomaly_text not in {"yes", "no"}:
            raise ValueError(f"{case['case_id']}: expected_anomaly must be Yes or No")
        expected_anomaly = expected_anomaly_text == "yes"
        expected_verdict = case["expected_verdict"].strip()
        expected_note_id = case["expected_note_id"].strip()
        if expected_verdict not in ALLOWED_VERDICTS:
            raise ValueError(f"{case['case_id']}: unsupported expected verdict {expected_verdict!r}")
        if (not expected_anomaly and expected_verdict != "not_anomaly") or (
            expected_anomaly and expected_verdict == "not_anomaly"
        ):
            raise ValueError(f"{case['case_id']}: inconsistent expected anomaly/verdict labels")
        if (expected_verdict == "justified") != bool(expected_note_id):
            raise ValueError(f"{case['case_id']}: only justified cases may carry an expected note ID")

        week = date.fromisoformat(case["week_of"])
        key = (case["route"], week)
        candidates = by_route_week.get(key, [])
        differences: list[str] = []
        actual_anomaly: bool | None = None
        actual_verdict = "not_found"
        actual_note_id = ""
        details = "No matching route/week group exists in shipment data."
        if week.weekday() != 0:
            raise ValueError(f"{case['case_id']}: week_of must be a Monday ISO date")
        if len(candidates) > 1:
            raise ValueError(f"{case['case_id']}: route/week maps to multiple route_type groups")
        if candidates:
            row = candidates[0]
            actual_anomaly = is_increase_anomaly(row, threshold)
            details = (
                f"rate={row['rate']}; own_baseline={row['own_baseline']}; "
                f"peer_baseline={row['peer_baseline']}"
            )
            if actual_anomaly:
                output_row = build_output_row(row, notes)
                validate_output([output_row], OUTPUT_COLUMNS)
                actual_note_id = output_row["matched_note_id"]
                actual_verdict = "justified" if output_row["flagged"] == "No (justified)" else "unexplained"
            else:
                actual_verdict = "not_anomaly"

        if actual_anomaly != expected_anomaly:
            differences.append(f"anomaly expected={expected_anomaly} actual={actual_anomaly}")
        if actual_verdict != expected_verdict:
            differences.append(f"verdict expected={expected_verdict!r} actual={actual_verdict!r}")
        if actual_note_id != expected_note_id:
            differences.append(f"matched_note_id expected={expected_note_id!r} actual={actual_note_id!r}")

        results.append({
            "case_id": case["case_id"],
            "passed": not differences,
            "expected_anomaly": expected_anomaly,
            "actual_anomaly": actual_anomaly,
            "expected_verdict": expected_verdict,
            "actual_verdict": actual_verdict,
            "expected_note_id": expected_note_id,
            "actual_note_id": actual_note_id,
            "details": details,
            "differences": differences,
            "manual_basis": case["manual_basis"],
        })
    return results, threshold


def main() -> int:
    results, threshold = evaluate_cases()
    total = len(results)
    passed = sum(bool(result["passed"]) for result in results)
    failed = total - passed
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} {result['case_id']}: {result['details']}")
        print(
            f"  anomaly expected={result['expected_anomaly']} actual={result['actual_anomaly']}; "
            f"verdict expected={result['expected_verdict']} actual={result['actual_verdict']}; "
            f"matched_note_id expected={result['expected_note_id'] or '(blank)'} "
            f"actual={result['actual_note_id'] or '(blank)'}"
        )
        if result["differences"]:
            for difference in result["differences"]:
                print(f"  MISMATCH: {difference}")
    rate = (passed / total * 100) if total else 0.0
    print(f"Threshold: {threshold}% (current configured value)")
    print(f"Evaluation: {total} cases; {passed} passed; {failed} failed; pass rate {rate:.1f}%.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
