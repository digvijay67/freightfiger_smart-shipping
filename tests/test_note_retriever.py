import unittest
from datetime import date

from src.config import NOTES_FILE
from src.data_loader import load_csv
from src.note_retriever import retrieve_notes


class NoteRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.notes = [
            {"note_id": "N1", "date": "2025-02-24", "applies_to": "Chennai-Bangalore",
             "note": "Heavy flooding disrupted movement from Feb 24 to Mar 8, forcing higher trip costs."},
            {"note_id": "N2", "date": "2025-09-22", "applies_to": "All Routes",
             "note": "Demand remained stable with no major disruptions."},
            {"note_id": "N3", "date": "2025-01-20", "applies_to": "Ahmedabad-Mumbai",
             "note": "A festival week saw a temporary surcharge."},
        ]

    def test_route_and_date_overlap_supported_note(self):
        found = retrieve_notes("Chennai-Bangalore", date(2025, 3, 3), self.notes)
        self.assertEqual([n["note_id"] for n in found], ["N1"])
        self.assertEqual(retrieve_notes("Chennai-Bangalore", date(2025, 3, 10), self.notes), [])

    def test_wrong_route_and_non_supporting_notes_rejected(self):
        self.assertEqual(retrieve_notes("Mumbai-Pune", date(2025, 1, 20), self.notes), [])
        self.assertEqual(retrieve_notes("Mumbai-Pune", date(2025, 9, 22), self.notes), [])

    def test_all_routes_positive_increase_note(self):
        notes = [{"note_id": "N4", "date": "2025-05-05", "applies_to": "All Routes",
                  "note": "Diesel prices rose starting this week, pushing up transportation costs 5-7%."}]
        self.assertEqual(retrieve_notes("Mumbai-Pune", date(2025, 5, 5), notes)[0]["note_id"], "N4")
        self.assertEqual(retrieve_notes("Mumbai-Pune", date(2025, 5, 12), notes), [])

    def test_route_dash_variants_and_explicit_negative_wording(self):
        notes = [{"note_id": "N5", "date": "2025-02-24", "applies_to": "Chennai–Bangalore",
                  "note": "A surcharge increased trip costs."}]
        self.assertEqual(retrieve_notes("Chennai-Bangalore", date(2025, 2, 24), notes)[0]["note_id"], "N5")
        for phrase in ("Costs did not rise.", "There was no surcharge.", "Rates remained unchanged."):
            negative = [{**notes[0], "note": f"A surcharge was discussed, but {phrase}"}]
            self.assertEqual(retrieve_notes("Chennai-Bangalore", date(2025, 2, 24), negative), [])

    def test_week_argument_must_be_monday(self):
        with self.assertRaises(ValueError):
            retrieve_notes("Chennai-Bangalore", date(2025, 2, 25), self.notes)

    def test_actual_input_notes_match_only_supporting_route_and_dates(self):
        notes = load_csv(NOTES_FILE)
        self.assertEqual([n["note_id"] for n in retrieve_notes(
            "Ahmedabad-Mumbai", date(2025, 1, 20), notes)], ["N002"])
        self.assertEqual([n["note_id"] for n in retrieve_notes(
            "Chennai-Bangalore", date(2025, 3, 3), notes)], ["N001"])
        unsupported = [
            ("Mumbai-Pune", "2024-03-11"),   # N004: affected routes outside this dataset
            ("Mumbai-Delhi", "2024-07-29"),  # N005: costs not significantly affected
            ("Mumbai-Pune", "2025-09-22"),   # N006: stable demand
            ("Delhi-Jaipur", "2024-05-20"),  # N007: improved road conditions
            ("Kolkata-Bhubaneswar", "2025-06-09"),  # N008: normal movement
            ("Chennai-Bangalore", "2025-03-17"),  # N009: returned to normal
            ("Mumbai-Pune", "2025-10-27"),   # N010: no rate change
        ]
        for route, monday in unsupported:
            with self.subTest(route=route, monday=monday):
                self.assertEqual(retrieve_notes(route, date.fromisoformat(monday), notes), [])


if __name__ == "__main__":
    unittest.main()
