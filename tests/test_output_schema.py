import tempfile
import unittest
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.config import OUTPUT_COLUMNS, REPORT_FILE, SAMPLE_OUTPUT_FILE, NOTES_FILE
from src.data_loader import load_csv
from src.explanation_generator import build_output_row
from src.main import validate_output
from src.note_retriever import retrieve_notes
from src.report_writer import sha256_file, write_report


class OutputSchemaTests(unittest.TestCase):
    def test_sample_header_exactly_matches_output_contract(self):
        with SAMPLE_OUTPUT_FILE.open(encoding="utf-8-sig", newline="") as stream:
            import csv
            self.assertEqual(next(csv.reader(stream)), OUTPUT_COLUMNS)

    def test_unexplained_increase_has_no_note_id_and_schema_order(self):
        weekly = {"route": "A-B", "week": date(2025, 1, 6), "rate": Decimal("3.2"),
                  "own_baseline": Decimal("2.5"), "peer_baseline": Decimal("2.6")}
        row = build_output_row(weekly, [])
        validate_output([row], OUTPUT_COLUMNS)
        self.assertEqual(list(row), OUTPUT_COLUMNS)
        self.assertEqual(row["matched_note_id"], "")
        self.assertEqual(row["flagged"], "Yes")

    def test_report_schema_value_formats_and_note_evidence(self):
        notes = load_csv(NOTES_FILE)
        with REPORT_FILE.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, OUTPUT_COLUMNS)
            rows = list(reader)
        validate_output(rows, OUTPUT_COLUMNS)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIsInstance(row["cost_per_tonne_km"], str)
            if row["flagged"] == "Yes":
                self.assertEqual(row["matched_note_id"], "")
            else:
                applicable_ids = {n["note_id"] for n in retrieve_notes(
                    row["route"], date.fromisoformat(row["week_of"]), notes
                )}
                self.assertIn(row["matched_note_id"], applicable_ids)

    def test_three_untouched_writes_are_byte_identical(self):
        rows = [{column: "" for column in OUTPUT_COLUMNS}]
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / f"run_{i}.csv" for i in range(1, 4)]
            for path in paths:
                write_report(path, OUTPUT_COLUMNS, rows)
            self.assertEqual(len({sha256_file(path) for path in paths}), 1)


if __name__ == "__main__":
    unittest.main()
