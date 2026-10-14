import csv
import shutil
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.config import (
    NOTES_FILE,
    OUTPUT_COLUMNS,
    REPORT_FILE,
    SAMPLE_OUTPUT_FILE,
    SHIPMENTS_FILE,
)
from src.main import build_report
from src.qa_assistant import QAAssistant, StaleResultsError, interactive_chat
from src.report_writer import sha256_file, write_report


def detail(route, monday, rate, own, peer, own_weeks=4, peer_routes=2):
    origin, destination = route.split("-")
    return {
        "route": route, "origin": origin, "destination": destination, "route_type": "Short",
        "week": date.fromisoformat(monday), "rate": Decimal(rate),
        "own_baseline": None if own is None else Decimal(own),
        "peer_baseline": None if peer is None else Decimal(peer),
        "own_weeks": own_weeks, "peer_routes": peer_routes,
    }


def output_row(route, monday, rate, own_text, peer_text, note_id="", flagged="Yes"):
    return {
        "route": route, "week_of": monday, "cost_per_tonne_km": rate,
        "vs_own_history": own_text, "vs_similar_routes": peer_text,
        "flagged": flagged, "matched_note_id": note_id,
        "reason": "A supplied context note supports this increase." if note_id else "Unexplained increase; no supporting note.",
    }


class QAAssistantTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            output_row("Ahmedabad-Mumbai", "2025-01-20", "3.29", "+29.5% vs history", "+22.5% vs peers", "N002", "No (justified)"),
            output_row("Chennai-Bangalore", "2025-02-24", "3.58", "+31.5% vs history", "+38.7% vs peers", "N001", "No (justified)"),
            output_row("Delhi-Jaipur", "2024-11-11", "4.17", "+35.5% vs history", "+21.0% vs peers"),
            output_row("Mumbai-Pune", "2025-09-15", "3.98", "+9.2% vs history", "+23.6% vs peers"),
            output_row("Mumbai-Pune", "2025-12-22", "4.49", "+5.7% vs history", "+38.9% vs peers"),
        ]
        self.details = [
            detail("Ahmedabad-Mumbai", "2025-01-20", "3.29", "2.54", "2.69"),
            detail("Chennai-Bangalore", "2025-02-24", "3.58", "2.72", "2.58"),
            detail("Delhi-Jaipur", "2024-11-11", "4.17", "3.08", "3.45"),
            detail("Mumbai-Pune", "2025-09-15", "3.98", "3.64", "3.22"),
            detail(
                "Mumbai-Pune", "2025-12-22", "4.485336320121254673821584001",
                "4.241496016340186023392175736", "3.228925363294389313171326360",
            ),
        ]
        self.notes = [
            {"note_id": "N001", "date": "2025-02-24", "applies_to": "Chennai-Bangalore",
             "note": "Flooding caused detours and higher trip costs from Feb 24 to Mar 8."},
            {"note_id": "N002", "date": "2025-01-20", "applies_to": "Ahmedabad-Mumbai",
             "note": "Festival demand led to a temporary surcharge."},
        ]
        self.hashes = ("a" * 64, "b" * 64)
        self.assistant = QAAssistant(self.rows, self.details, self.notes, self.hashes, lambda: self.hashes)

    def test_basic_anomaly_count_and_route_listing(self):
        self.assertIn("5 anomaly row(s)", self.assistant.answer("How many anomalies are there?"))
        answer = self.assistant.answer("Which routes have unusual shipping costs?")
        self.assertIn("Ahmedabad-Mumbai", answer)
        self.assertIn("Mumbai-Pune", answer)

    def test_summary_distinguishes_supported_from_unexplained(self):
        answer = self.assistant.answer("Summarize the findings for a non-technical audience")
        self.assertIn("2 have a route/date-matched context note", answer)
        self.assertIn("3 have no supporting note", answer)

    def test_specific_explanation_uses_actual_route_date_note(self):
        answer = self.assistant.answer("Why was Ahmedabad-Mumbai flagged on 2025-01-20?")
        self.assertIn("N002", answer)
        self.assertIn("temporary surcharge", answer)
        self.assertIn("not proof of causation", answer)

    def test_exact_mumbai_pune_more_details_question_uses_report_row(self):
        answer = self.assistant.answer("Tell me more about Mumbai-Pune for the week of 2025-12-22.")
        self.assertIn("Mumbai-Pune for week 2025-12-22", answer)
        self.assertIn("4.49 INR/tonne-km", answer)
        self.assertIn("+38.9% vs peers", answer)
        self.assertIn("unexplained (no supporting note)", answer)
        self.assertNotIn("N00", answer)

    def test_natural_language_route_date_variants_use_same_report_row(self):
        questions = [
            "Explain the Mumbai-Pune anomaly from 2025-12-22.",
            "Show details for Mumbai-Pune on 2025-12-22.",
            "Why was Mumbai-Pune flagged on 2025-12-22?",
        ]
        for question in questions:
            with self.subTest(question=question):
                answer = self.assistant.answer(question)
                self.assertIn("Mumbai-Pune for week 2025-12-22", answer)
                self.assertIn("4.49 INR/tonne-km", answer)
                self.assertIn("unexplained (no supporting note)", answer)

    def test_last_anomaly_means_final_row_in_current_report_order(self):
        answer = self.assistant.answer("Tell me more about the last anomaly.")
        self.assertIn("Mumbai-Pune for week 2025-12-22", answer)
        self.assertIn("4.49 INR/tonne-km", answer)
        self.assertNotIn("5 anomaly row(s)", answer)

    def test_specific_detail_request_without_date_requires_clarification_when_ambiguous(self):
        answer = self.assistant.answer("Tell me more about Mumbai-Pune.")
        self.assertIn("multiple anomalies", answer)
        self.assertIn("include an ISO date or week", answer)

    def test_unknown_route_date_and_known_route_without_anomaly_return_no_match(self):
        unknown = self.assistant.answer("Why was Pune-Delhi flagged on 2025-01-06?")
        self.assertEqual(
            unknown,
            "No data found for the Pune-Delhi route in the week of 2025-01-06. "
            "I cannot verify that it was flagged.",
        )
        self.assertNotIn("N001", unknown)
        no_anomaly = self.assistant.answer("Show details for Mumbai-Pune on 2025-01-06.")
        self.assertIn("No anomaly row matches that route and week", no_anomaly)
        self.assertNotIn("4.49 INR/tonne-km", no_anomaly)

    def test_unknown_route_with_explicit_month_returns_clear_no_data(self):
        answer = self.assistant.answer("Why was the Pune-Goa route flagged in December 2025?")
        self.assertEqual(
            answer,
            "No data found for the Pune-Goa route in December 2025. "
            "I cannot verify that it was flagged.",
        )
        self.assertNotIn("INR/tonne-km", answer)
        self.assertNotIn("N00", answer)

    def test_unknown_route_with_explicit_week_does_not_request_route_again(self):
        answer = self.assistant.answer("Why was Pune-Goa flagged in the week of 2025-12-08?")
        self.assertEqual(
            answer,
            "No data found for the Pune-Goa route in the week of 2025-12-08. "
            "I cannot verify that it was flagged.",
        )
        self.assertNotIn("Please name the route", answer)
        self.assertNotIn("N00", answer)

    def test_valid_route_with_explicit_month_still_uses_report_and_note(self):
        answer = self.assistant.answer("Why was Ahmedabad-Mumbai flagged in January 2025?")
        self.assertIn("Ahmedabad-Mumbai for week 2025-01-20", answer)
        self.assertIn("3.29 INR/tonne-km", answer)
        self.assertIn("N002", answer)
        self.assertIn("not proof of causation", answer)

    def test_note_question_for_existing_anomaly_without_support_stays_unexplained(self):
        answer = self.assistant.answer(
            "Which context note explains the Mumbai-Pune anomaly for the week of 2025-12-22?"
        )
        self.assertEqual(
            answer,
            "Mumbai-Pune was flagged for the week of 2025-12-22, with a cost of 4.49 INR/tonne-km. "
            "It increased by 5.7% versus its historical baseline and 38.9% versus peer routes. "
            "No eligible context note supports this anomaly, so the cause remains unexplained.",
        )
        self.assertNotIn("N00", answer)

    def test_note_question_for_supported_anomaly_returns_eligible_note(self):
        answer = self.assistant.answer(
            "Since a festival caused the Ahmedabad-Mumbai anomaly on 2025-01-20, "
            "which context note proves it?"
        )
        self.assertIn("Ahmedabad-Mumbai was flagged for the week of 2025-01-20", answer)
        self.assertIn("Eligible context note N002 states", answer)
        self.assertIn("temporary surcharge", answer)
        self.assertIn("not proof of causation", answer)

    def test_misleading_festival_premise_does_not_create_support_for_unexplained_anomaly(self):
        answer = self.assistant.answer(
            "Since the Mumbai-Pune anomaly on 2025-12-22 was caused by a festival, "
            "which context note proves it?"
        )
        self.assertEqual(
            answer,
            "Mumbai-Pune was flagged for the week of 2025-12-22, with a cost of 4.49 INR/tonne-km. "
            "It increased by 5.7% versus its historical baseline and 38.9% versus peer routes. "
            "No eligible context note proves that a festival caused this anomaly, "
            "so the cause remains unexplained.",
        )
        self.assertNotIn("N00", answer)
        self.assertNotIn("No matching anomalies of that evidence type", answer)

    def test_causal_question_uses_supported_flood_note_without_claiming_proof(self):
        assistant = QAAssistant.load_current()
        answer = assistant.answer(
            "N001 says roads were passable again by March 9, but can we still conclude "
            "that flooding caused the Chennai-Bangalore anomaly on 2025-03-03?"
        )
        self.assertIn("Chennai-Bangalore was flagged for the week of 2025-03-03", answer)
        self.assertIn("Note N001", answer)
        self.assertIn("from Feb 24 to Mar 8", answer)
        self.assertIn("passable again by Mar 9", answer)
        self.assertIn("supports flooding as relevant context", answer)
        self.assertIn("does not prove flooding caused the anomaly", answer)
        self.assertNotIn("anomaly row(s) across", answer)

    def test_causal_question_without_eligible_note_remains_unexplained(self):
        answer = self.assistant.answer(
            "Can we be certain a festival caused the Mumbai-Pune anomaly on 2025-12-22?"
        )
        self.assertIn("No eligible context note supports a causal conclusion", answer)
        self.assertIn("cause remains unexplained", answer)
        self.assertNotIn("N00", answer)

    def test_causal_question_rejects_out_of_window_note(self):
        assistant = QAAssistant.load_current()
        answer = assistant.answer(
            "N009 says the route returned to normal, does this prove it caused the "
            "Chennai-Bangalore anomaly on 2025-03-03?"
        )
        self.assertIn("N009 is not eligible", answer)
        self.assertIn("cannot support or prove the cause", answer)
        self.assertNotIn("returned to normal conditions after flood-related repairs", answer)

    def test_note_question_for_route_week_without_anomaly_returns_no_match(self):
        answer = self.assistant.answer(
            "Which context note explains the Mumbai-Pune anomaly for the week of 2025-01-06?"
        )
        self.assertIn("No matching anomaly was found", answer)
        self.assertIn("Mumbai-Pune", answer)
        self.assertIn("week of 2025-01-06", answer)
        self.assertNotIn("N00", answer)

    def test_three_examples_are_real_distinct_report_rows(self):
        answer = self.assistant.answer("Show me three representative anomalies")
        self.assertIn("Three representative examples", answer)
        chosen_rows = [
            (row["route"], row["week_of"])
            for row in self.rows
            if f"{row['route']} for week {row['week_of']}" in answer
        ]
        self.assertEqual(len(chosen_rows), 3)
        self.assertEqual(len(set(chosen_rows)), 3)
        self.assertEqual(len({route for route, _ in chosen_rows}), 3)
        self.assertEqual(sum(answer.count(f"{index}. ") for index in range(1, 4)), 3)

    def test_supported_and_unsupported_note_questions(self):
        supported = self.assistant.answer("Which anomalies have supporting context notes?")
        self.assertIn("N001", supported)
        self.assertIn("N002", supported)
        unsupported = self.assistant.answer("Which anomalies have no supporting evidence?")
        self.assertIn("Delhi-Jaipur", unsupported)
        self.assertNotIn("N006", unsupported)

    def test_missing_route_or_evidence_is_not_invented(self):
        answer = self.assistant.answer("Why was Bengaluru-Kochi flagged?")
        self.assertIn("Please name the route", answer)
        self.assertNotIn("N", answer)

    def test_unknown_and_multiple_routes_are_handled_gracefully(self):
        self.assertIn("could not map", self.assistant.answer("What is tomorrow's weather?"))
        self.assertIn("multiple routes", self.assistant.answer("Compare Delhi-Jaipur with Mumbai-Pune"))

    def test_baselines_and_largest_increase_use_numeric_details(self):
        baselines = self.assistant.answer("What are the historical and peer baselines for Mumbai-Pune?")
        self.assertIn("3.6400 INR/tonne-km", baselines)
        largest = self.assistant.answer("Which route had the largest cost-per-tonne-km increase?")
        self.assertIn("Largest increase versus historical (own-history) baseline", largest)
        self.assertIn("Delhi-Jaipur", largest)
        self.assertIn("Largest increase versus same-week peer baseline", largest)
        self.assertIn("Mumbai-Pune", largest)
        self.assertIn("2025-12-22", largest)
        self.assertIn("up 38.9%", largest)

    def test_baseline_definitions_do_not_require_a_route(self):
        answer = self.assistant.answer("What is the difference between historical and peer baselines?")
        self.assertIn("only weeks strictly before the current week", answer)
        self.assertIn("without padding or extrapolation", answer)
        self.assertIn("same week across all other routes", answer)
        self.assertIn("excluding the current route", answer)

    def test_largest_increase_questions_keep_baseline_labels_separate(self):
        own_history = self.assistant.answer("Which route had the largest increase versus its historical baseline?")
        self.assertIn("Delhi-Jaipur", own_history)
        self.assertIn("versus historical (own-history) baseline", own_history)
        self.assertNotIn("peer baseline", own_history)

        peers = self.assistant.answer("Which route had the largest increase versus its peer baseline?")
        self.assertIn("Mumbai-Pune", peers)
        self.assertIn("versus same-week peer baseline", peers)
        self.assertNotIn("historical (own-history) baseline", peers)

    def test_unknown_route_baseline_question_returns_no_data(self):
        answer = self.assistant.answer("What are the historical and peer baselines for Pune-Delhi?")
        self.assertIn("couldn't find route Pune-Delhi", answer)
        self.assertNotIn("INR/tonne-km", answer)
        self.assertNotIn("N001", answer)

    def test_input_change_during_session_stops_answers(self):
        hashes = list(self.hashes)
        assistant = QAAssistant(self.rows, self.details, self.notes, self.hashes, lambda: tuple(hashes))
        hashes[0] = "c" * 64
        with self.assertRaises(StaleResultsError):
            assistant.answer("How many anomalies?")

    def test_actual_report_loads_and_retains_all_rows(self):
        assistant = QAAssistant.load_current()
        with REPORT_FILE.open(encoding="utf-8-sig", newline="") as stream:
            saved = list(csv.DictReader(stream))
        self.assertEqual(len(assistant.rows), len(saved))
        self.assertEqual(len(assistant.rows), 20)
        self.assertIn("N002", assistant.answer("Why was Ahmedabad-Mumbai flagged on 2025-01-20?"))

    def test_stale_report_from_changed_inputs_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            shipments = temp / "shipment_records.csv"
            notes = temp / "context_notes.csv"
            report = temp / "anomaly_report.csv"
            evidence = temp / "reproducibility_check.txt"
            shutil.copyfile(SHIPMENTS_FILE, shipments)
            shutil.copyfile(NOTES_FILE, notes)
            from src.data_loader import load_csv
            from src.main import NOTE_COLUMNS, SHIPMENT_COLUMNS
            shipment_rows = load_csv(shipments, set(SHIPMENT_COLUMNS), expected_columns=SHIPMENT_COLUMNS,
                                     nonempty_columns=set(SHIPMENT_COLUMNS))
            note_rows = load_csv(notes, set(NOTE_COLUMNS), expected_columns=NOTE_COLUMNS,
                                 nonempty_columns=set(NOTE_COLUMNS))
            report_rows = build_report(shipment_rows, note_rows, Decimal("20"))
            write_report(report, OUTPUT_COLUMNS, report_rows)
            ship_hash, note_hash = sha256_file(shipments), sha256_file(notes)
            evidence.write_text(
                f"Threshold: 20%\nshipment_records.csv SHA-256 before/after: {ship_hash} / {ship_hash}\n"
                f"context_notes.csv SHA-256 before/after: {note_hash} / {note_hash}\n",
                encoding="utf-8",
            )
            tampered_rows = [dict(row) for row in report_rows]
            tampered_rows[0]["cost_per_tonne_km"] = "99.00"
            write_report(report, OUTPUT_COLUMNS, tampered_rows)
            with self.assertRaises(StaleResultsError):
                QAAssistant.load_current(
                    shipments_path=shipments, notes_path=notes, report_path=report,
                    evidence_path=evidence, sample_path=SAMPLE_OUTPUT_FILE,
                )
            write_report(report, OUTPUT_COLUMNS, report_rows)
            assistant = QAAssistant.load_current(
                shipments_path=shipments, notes_path=notes, report_path=report,
                evidence_path=evidence, sample_path=SAMPLE_OUTPUT_FILE,
            )
            with shipments.open("a", encoding="utf-8") as stream:
                stream.write("\n")
            with self.assertRaises(StaleResultsError):
                assistant.answer("How many anomalies?")
            with self.assertRaises(StaleResultsError):
                QAAssistant.load_current(
                    shipments_path=shipments, notes_path=notes, report_path=report,
                    evidence_path=evidence, sample_path=SAMPLE_OUTPUT_FILE,
                )

    def test_multi_question_session_keeps_route_context(self):
        first = self.assistant.answer("Tell me about Mumbai-Pune anomalies")
        second = self.assistant.answer("What were this route's historical and peer baselines?")
        self.assertIn("Mumbai-Pune", first)
        self.assertIn("Mumbai-Pune", second)

    def test_interactive_loop_accepts_multiple_questions_and_exit(self):
        answers = iter(["Tell me about Mumbai-Pune anomalies", "What were this route's baselines?", "exit"])
        with patch.object(QAAssistant, "load_current", return_value=self.assistant), \
             patch("builtins.input", side_effect=lambda _prompt: next(answers)), \
             patch("builtins.print") as printer:
            interactive_chat("20")
        printed = "\n".join(str(call.args[0]) for call in printer.call_args_list if call.args)
        self.assertIn("Mumbai-Pune", printed)
        self.assertIn("Goodbye.", printed)


if __name__ == "__main__":
    unittest.main()
