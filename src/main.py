"""Build the anomaly report and verify three independent run artifacts."""
import argparse
import csv
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.anomaly_detector import enrich_with_baselines, is_increase_anomaly
from src.config import (ANOMALY_THRESHOLD_PCT, NOTES_FILE, OUTPUT_COLUMNS, OUTPUT_DIR, ROOT,
                        REPORT_FILE, REPRODUCIBILITY_FILE, SAMPLE_OUTPUT_FILE,
                        SHIPMENTS_FILE, TOKEN_LOG_FILE)
from src.cost_calculator import calculate_weekly_rates
from src.data_loader import load_csv
from src.explanation_generator import build_output_row
from src.local_rag import LocalRagNotes, summarize_usage
from src.report_writer import sha256_file, write_report

SHIPMENT_COLUMNS = ["shipment_id", "origin", "destination", "route_type", "material",
                    "quantity_tonnes", "distance_km", "freight_cost_inr", "shipment_date", "transporter"]
NOTE_COLUMNS = ["note_id", "date", "applies_to", "note"]


def parse_threshold(value: str) -> Decimal:
    try:
        threshold = Decimal(value)
    except InvalidOperation:
        raise ValueError("Threshold must be a non-negative number (percent).") from None
    if not threshold.is_finite() or threshold < 0:
        raise ValueError("Threshold must be a finite non-negative number (percent).")
    return threshold


def build_report(
    shipments: list[dict[str, str]],
    notes: list[dict[str, str]],
    threshold: Decimal,
    rag_service: LocalRagNotes | None = None,
) -> list[dict[str, str]]:
    weekly = calculate_weekly_rates(shipments)
    enriched = enrich_with_baselines(weekly)
    anomalies = [row for row in enriched if is_increase_anomaly(row, threshold)]
    return [build_output_row(row, notes, rag_service) for row in anomalies]


def validate_output(rows: list[dict[str, str]], sample_columns: list[str]) -> None:
    if sample_columns != OUTPUT_COLUMNS:
        raise ValueError(f"Configured schema differs from sample: {sample_columns!r}")
    for index, row in enumerate(rows, 1):
        if list(row) != sample_columns:
            raise ValueError(f"Output row {index} has incorrect column order/schema")
        if not row["route"] or not row["week_of"]:
            raise ValueError(f"Output row {index} lacks route/week")
        try:
            week = date.fromisoformat(row["week_of"])
        except ValueError:
            raise ValueError(f"Output row {index} week_of is not an ISO date") from None
        if week.isoformat() != row["week_of"] or week.weekday() != 0:
            raise ValueError(f"Output row {index} week_of must be a Monday ISO date")
        if not re.fullmatch(r"\d+\.\d{2}", row["cost_per_tonne_km"]):
            raise ValueError(f"Output row {index} rate must be formatted as a two-decimal numeric string")
        Decimal(row["cost_per_tonne_km"])
        for column in ("vs_own_history", "vs_similar_routes"):
            if not re.fullmatch(r"(?:[+-]\d+\.\d% vs .+|N/A vs .+ \(baseline unavailable\))", row[column]):
                raise ValueError(f"Output row {index} has invalid comparison text in {column}")
        if row["flagged"] not in {"Yes", "No (justified)"}:
            raise ValueError(f"Unexpected flag value in output row {index}")
        if row["flagged"] == "Yes" and row["matched_note_id"]:
            raise ValueError("Unexplained rows must not contain a matched note ID")
        if row["flagged"] == "No (justified)" and not row["matched_note_id"]:
            raise ValueError("Justified rows must identify their supporting note")
        if not isinstance(row["reason"], str) or not row["reason"].strip():
            raise ValueError(f"Output row {index} requires a text reason")


def _sample_columns() -> list[str]:
    with SAMPLE_OUTPUT_FILE.open("r", encoding="utf-8-sig", newline="") as stream:
        return next(csv.reader(stream))


def _input_hashes() -> tuple[str, str]:
    return sha256_file(SHIPMENTS_FILE), sha256_file(NOTES_FILE)


def _validate_source_records(shipments: list[dict[str, str]], notes: list[dict[str, str]]) -> None:
    for records, key, label in ((shipments, "shipment_id", "shipment"), (notes, "note_id", "note")):
        identifiers = [row[key] for row in records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"Duplicate {label} identifier in source CSV")
    for row in notes:
        try:
            parsed = date.fromisoformat(row["date"])
        except ValueError:
            raise ValueError(f"Note {row['note_id']} has an invalid ISO date") from None
        if parsed.isoformat() != row["date"]:
            raise ValueError(f"Note {row['note_id']} date must use YYYY-MM-DD")


def _fresh_run(
    filename: str,
    threshold_text: str,
    sample_columns: list[str],
    output_dir=OUTPUT_DIR,
    usage_file: Path | None = None,
) -> None:
    """Worker entry point. Each invocation reloads the original CSV inputs."""
    threshold = parse_threshold(threshold_text)
    shipments = load_csv(SHIPMENTS_FILE, set(SHIPMENT_COLUMNS), expected_columns=SHIPMENT_COLUMNS,
                         nonempty_columns=set(SHIPMENT_COLUMNS))
    notes = load_csv(NOTES_FILE, set(NOTE_COLUMNS), expected_columns=NOTE_COLUMNS,
                     nonempty_columns=set(NOTE_COLUMNS))
    _validate_source_records(shipments, notes)
    rag_service = LocalRagNotes()
    rows = build_report(shipments, notes, threshold, rag_service)
    validate_output(rows, sample_columns)
    write_report(output_dir / filename, sample_columns, rows)
    if usage_file is not None:
        usage_file.parent.mkdir(parents=True, exist_ok=True)
        usage_file.write_text(json.dumps(summarize_usage([rag_service]), sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold-pct", default=ANOMALY_THRESHOLD_PCT,
                        help="Increase threshold in percent; default 20 (explicit implementation assumption).")
    parser.add_argument("--chat", action="store_true",
                        help="Start an interactive Q&A session over the current verified anomaly report.")
    parser.add_argument("--_worker-output", help=argparse.SUPPRESS)
    parser.add_argument("--_worker-dir", default=str(OUTPUT_DIR), help=argparse.SUPPRESS)
    parser.add_argument("--_worker-usage-file", help=argparse.SUPPRESS)
    args = parser.parse_args()
    threshold = parse_threshold(args.threshold_pct)
    sample_columns = _sample_columns()
    if args.chat:
        if args._worker_output is not None:
            parser.error("--chat cannot be combined with internal worker arguments")
        from src.qa_assistant import interactive_chat
        interactive_chat(str(threshold))
        return
    if args._worker_output is not None:
        if args._worker_output not in {f"run_{i}.csv" for i in range(1, 4)}:
            parser.error("internal worker output name is invalid")
        _fresh_run(
            args._worker_output,
            str(threshold),
            sample_columns,
            Path(args._worker_dir),
            Path(args._worker_usage_file) if args._worker_usage_file else None,
        )
        return

    # Each child process reloads the original input files independently.
    input_hashes_before = _input_hashes()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = []
    run_usage = []
    with tempfile.TemporaryDirectory(prefix="freighttiger-rag-candidate-", dir=OUTPUT_DIR) as run_dir:
        for number in range(1, 4):
            filename = f"run_{number}.csv"
            usage_path = Path(run_dir) / f"run_{number}.json"
            command = [sys.executable, "-m", "src.main", "--threshold-pct", str(threshold),
                       "--_worker-output", filename, "--_worker-dir", run_dir,
                       "--_worker-usage-file", str(usage_path)]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
            path = Path(run_dir) / filename
            validate_output(load_csv(path, set(sample_columns), expected_columns=sample_columns), sample_columns)
            outputs.append((path, sha256_file(path)))
            run_usage.append(json.loads(usage_path.read_text(encoding="utf-8")))
    if len({digest for _, digest in outputs}) != 1:
        raise RuntimeError("Three-run reproducibility check failed")
    input_hashes_after = _input_hashes()
    if input_hashes_after != input_hashes_before:
        raise RuntimeError("Input CSV files changed during reproducibility runs")
    committed_outputs = []
    for path, digest in outputs:
        destination = OUTPUT_DIR / path.name
        os.replace(path, destination)
        committed_outputs.append((destination, digest))
    staged_report = OUTPUT_DIR / ".anomaly_report.csv.tmp"
    staged_report.write_bytes(committed_outputs[0][0].read_bytes())
    os.replace(staged_report, REPORT_FILE)
    shipment_count = len(load_csv(SHIPMENTS_FILE, set(SHIPMENT_COLUMNS), expected_columns=SHIPMENT_COLUMNS,
                                  nonempty_columns=set(SHIPMENT_COLUMNS)))
    note_count = len(load_csv(NOTES_FILE, set(NOTE_COLUMNS), expected_columns=NOTE_COLUMNS,
                              nonempty_columns=set(NOTE_COLUMNS)))
    REPRODUCIBILITY_FILE.write_text(
        "Three fresh Python subprocess runs; each process independently reloaded the original source CSV files.\n"
        f"Python: {platform.python_version()}\nThreshold: {threshold}% (configurable; implementation default, not from case brief)\n"
        f"Input rows: {shipment_count} shipments; {note_count} notes\n"
        f"shipment_records.csv SHA-256 before/after: {input_hashes_before[0]} / {input_hashes_after[0]}\n"
        f"context_notes.csv SHA-256 before/after: {input_hashes_before[1]} / {input_hashes_after[1]}\n"
        + "\n".join(f"{path.name} SHA-256: {digest}" for path, digest in committed_outputs)
        + "\nResult: byte-identical.\n",
        encoding="utf-8",
    )
    usage = {
        key: sum(int(run.get(key, 0) or 0) for run in run_usage)
        for key in ("ollama_chat_calls", "ollama_embedding_calls", "input_tokens", "output_tokens")
    }
    chat_models = sorted({model for run in run_usage for model in run.get("chat_models", [])})
    embedding_models = sorted({model for run in run_usage for model in run.get("embedding_models", [])})
    reported_embedding_tokens = all(run.get("embedding_tokens_reported", False) for run in run_usage)
    usage["embedding_tokens"] = (
        sum(int(run.get("embedding_tokens", 0) or 0) for run in run_usage)
        if reported_embedding_tokens else None
    )
    diagnostic_counts = {}
    for run in run_usage:
        for code, count in run.get("diagnostics", {}).items():
            diagnostic_counts[code] = diagnostic_counts.get(code, 0) + count
    diagnostics_text = "\n".join(
        f"- `{code}`: {count}" for code, count in sorted(diagnostic_counts.items())
    ) or "- No fallback or unexplained cases recorded."
    diagnostic_messages = [message for run in run_usage for message in run.get("diagnostic_messages", [])]
    diagnostic_detail_text = "\n".join(f"- {message}" for message in diagnostic_messages)
    embedding_tokens_text = str(usage["embedding_tokens"]) if usage["embedding_tokens"] is not None else "not reported by the Ollama embedding endpoint"
    TOKEN_LOG_FILE.write_text(
        "# Token and cost log\n\n"
        "This record covers the three independent subprocesses used for the reproducibility run. "
        "Counts are summed from Ollama response usage fields; embedding token counts are included only "
        "when the local endpoint reports them.\n\n"
        f"- Ollama chat calls: {usage['ollama_chat_calls']}\n"
        f"- Ollama embedding requests: {usage['ollama_embedding_calls']}\n"
        f"- Chat model(s) configured: {', '.join(chat_models) if chat_models else 'none'}\n"
        f"- Embedding model(s) configured: {', '.join(embedding_models) if embedding_models else 'none'}\n"
        f"- Chat input tokens reported: {usage['input_tokens']}\n"
        f"- Chat output tokens reported: {usage['output_tokens']}\n"
        f"- Embedding tokens reported: {embedding_tokens_text}\n"
        "- Direct hosted API charges: $0.00 (local Ollama; electricity/hardware cost excluded)\n"
        "- Published hosted-model rate: not applicable to local inference\n\n"
        "## Diagnostic outcomes\n\n" + diagnostics_text + "\n"
        + ("\n## Diagnostic details\n\n" + diagnostic_detail_text + "\n" if diagnostic_detail_text else ""),
        encoding="utf-8",
    )
    print(f"Wrote {len(load_csv(REPORT_FILE, set(sample_columns), expected_columns=sample_columns))} anomaly rows to {REPORT_FILE}")
    print("Three run files are byte-identical.")


if __name__ == "__main__":
    main()
