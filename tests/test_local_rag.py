import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from src.config import NOTES_FILE, OUTPUT_COLUMNS
from src.data_loader import load_csv
from src.explanation_generator import build_output_row
from src.local_rag import LocalRagNotes, RagSettings
from src.qa_assistant import _report_matches_calculation


class LocalRagTests(unittest.TestCase):
    def setUp(self):
        self.notes = load_csv(NOTES_FILE)
        self.enabled = RagSettings(
            base_url="http://localhost:11434", embedding_model="test-embed",
            chat_model="test-chat", timeout_seconds=0.1, top_k=3,
            minimum_similarity=0.0, seed=42,
        )

    def test_hard_route_and_date_filters_precede_rag(self):
        service = LocalRagNotes(self.enabled)
        for route, week in (("Mumbai-Pune", date(2025, 1, 20)),
                            ("Chennai-Bangalore", date(2025, 3, 10))):
            candidates = service.note_candidates(route, week, self.notes)
            self.assertEqual(candidates, [])
            with patch.object(service, "_post") as post:
                self.assertIsNone(service.explain(route, week, candidates))
                post.assert_not_called()
        self.assertEqual(service.diagnostics.get("unexplained_no_eligible_note"), 2)

    def test_actual_route_date_supported_notes_are_eligible(self):
        service = LocalRagNotes(self.enabled)
        self.assertEqual(
            [n["note_id"] for n in service.note_candidates("Ahmedabad-Mumbai", date(2025, 1, 20), self.notes)],
            ["N002"],
        )
        self.assertEqual(
            [n["note_id"] for n in service.note_candidates("Chennai-Bangalore", date(2025, 3, 3), self.notes)],
            ["N001"],
        )

    def test_note_saying_costs_were_unaffected_is_not_evidence(self):
        neutral = [{"note_id": "N-test", "date": "2025-01-20", "applies_to": "A-B",
                    "note": "A temporary surcharge was discussed, but costs were unaffected."}]
        service = LocalRagNotes(self.enabled)
        candidates = service.note_candidates("A-B", date(2025, 1, 20), neutral)
        self.assertEqual(candidates, [])
        with patch.object(service, "_post") as post:
            self.assertIsNone(service.explain("A-B", date(2025, 1, 20), candidates))
            post.assert_not_called()

    def test_unavailable_ollama_uses_observable_fallback(self):
        service = LocalRagNotes(self.enabled)
        candidates = service.note_candidates("Ahmedabad-Mumbai", date(2025, 1, 20), self.notes)
        with patch.object(service, "_post", side_effect=RuntimeError("offline")):
            self.assertIsNone(service.explain("Ahmedabad-Mumbai", date(2025, 1, 20), candidates))
        self.assertEqual(service.diagnostics.get("fallback_rag_failure"), 1)

    def test_timeout_and_invalid_model_id_fail_back_to_deterministic_path(self):
        service = LocalRagNotes(self.enabled)
        candidates = service.note_candidates("Ahmedabad-Mumbai", date(2025, 1, 20), self.notes)
        with patch("src.local_rag.urlopen", side_effect=TimeoutError("timed out")):
            self.assertIsNone(service.explain("Ahmedabad-Mumbai", date(2025, 1, 20), candidates))
        self.assertEqual(service.diagnostics.get("fallback_rag_failure"), 1)

        service = LocalRagNotes(self.enabled)
        with patch.object(service, "_post") as post:
            post.side_effect = [
                {"embeddings": [[1.0, 0.0], [1.0, 0.0]]},
                {"message": {"content": '{"note_id":"FAKE","explanation":"A regional festival week saw a surcharge","evidence_quote":"A regional festival week saw a surcharge"}'}},
            ]
            self.assertIsNone(service.explain("Ahmedabad-Mumbai", date(2025, 1, 20), candidates))
        self.assertEqual(service.diagnostics.get("fallback_rag_failure"), 1)
        self.assertIn("not among", service.diagnostic_messages[-1])

    def test_invalid_or_unsupported_model_output_is_rejected(self):
        note = {"note_id": "N2", "date": "2025-01-20", "applies_to": "A-B",
                "note": "Temporary surcharge applied and higher trip costs were reported."}
        with self.assertRaisesRegex(ValueError, "not among"):
            LocalRagNotes._validate_generated(
                {"note_id": "N1", "explanation": "Temporary surcharge applied",
                 "evidence_quote": "Temporary surcharge applied"}, [note])
        with self.assertRaisesRegex(ValueError, "exact substring"):
            LocalRagNotes._validate_generated(
                {"note_id": "N2", "explanation": "Temporary surcharge applied",
                 "evidence_quote": "A surcharge raised costs"}, [note])
        with self.assertRaisesRegex(ValueError, "words absent"):
            LocalRagNotes._validate_generated(
                {"note_id": "N2", "explanation": "A cyclone caused the increase",
                 "evidence_quote": "Temporary surcharge applied"}, [note])

    def test_valid_output_uses_retrieved_note_and_measured_usage(self):
        service = LocalRagNotes(self.enabled)
        note = {"note_id": "N2", "date": "2025-01-20", "applies_to": "A-B",
                "note": "A temporary surcharge applied due to high demand and increased trip costs."}
        with patch.object(service, "_post") as post:
            post.side_effect = [
                {"embeddings": [[1.0, 0.0], [1.0, 0.0]]},
                {"prompt_eval_count": 23, "eval_count": 10,
                 "message": {"content": '{"note_id":"N2","explanation":"A temporary surcharge applied due to high demand","evidence_quote":"A temporary surcharge applied"}'}},
            ]
            result = service.explain("A-B", date(2025, 1, 20), [note])
        self.assertEqual(result["note_id"], "N2")
        self.assertEqual(service.usage["ollama_embedding_calls"], 1)
        self.assertEqual(service.usage["ollama_chat_calls"], 1)
        self.assertEqual((service.usage["input_tokens"], service.usage["output_tokens"]), (23, 10))

    def test_report_schema_and_numeric_decision_are_unchanged_on_fallback(self):
        row = {"route": "Ahmedabad-Mumbai", "week": date(2025, 1, 20),
               "rate": Decimal("3.29"), "own_baseline": Decimal("2.54"),
               "peer_baseline": Decimal("2.68")}
        deterministic = build_output_row(row, self.notes)
        service = LocalRagNotes(self.enabled)
        with patch.object(service, "_post", side_effect=RuntimeError("offline")):
            fallback = build_output_row(row, self.notes, service)
        self.assertEqual(list(deterministic), OUTPUT_COLUMNS)
        self.assertEqual(list(fallback), OUTPUT_COLUMNS)
        for key in ("route", "week_of", "cost_per_tonne_km", "vs_own_history",
                    "vs_similar_routes", "flagged", "matched_note_id"):
            self.assertEqual(fallback[key], deterministic[key])
        self.assertEqual(fallback["flagged"], "No (justified)")
        self.assertEqual(fallback["matched_note_id"], "N002")

    def test_no_eligible_note_keeps_unexplained_verdict_and_blank_id(self):
        row = {"route": "Mumbai-Pune", "week": date(2025, 1, 20),
               "rate": Decimal("3.29"), "own_baseline": Decimal("2.54"),
               "peer_baseline": Decimal("2.68")}
        service = LocalRagNotes(self.enabled)
        with patch.object(service, "_post") as post:
            output = build_output_row(row, self.notes, service)
            post.assert_not_called()
        self.assertEqual(output["flagged"], "Yes")
        self.assertEqual(output["matched_note_id"], "")
        self.assertIn("unexplained", output["reason"])

    def test_qa_freshness_accepts_only_source_quoted_rag_reason(self):
        row = {"route": "Ahmedabad-Mumbai", "week": date(2025, 1, 20),
               "rate": Decimal("3.29"), "own_baseline": Decimal("2.54"),
               "peer_baseline": Decimal("2.68")}
        expected = build_output_row(row, self.notes)
        actual = dict(expected)
        actual["reason"] = (
            "Matches note N002 dated 2025-01-20: A regional festival week saw a temporary surcharge. "
            "Evidence quote: A regional festival week saw a temporary surcharge"
        )
        self.assertTrue(_report_matches_calculation([actual], [expected], self.notes))
        actual["reason"] += " creating a cyclone-related shortage"
        self.assertFalse(_report_matches_calculation([actual], [expected], self.notes))

    def test_qa_freshness_accepts_another_eligible_retrieved_note_id(self):
        row = {"route": "Ahmedabad-Mumbai", "week": date(2025, 1, 20),
               "rate": Decimal("3.29"), "own_baseline": Decimal("2.54"),
               "peer_baseline": Decimal("2.68")}
        notes = self.notes + [{
            "note_id": "N000", "date": "2025-01-20", "applies_to": "Ahmedabad-Mumbai",
            "note": "A festival surcharge led to higher trip costs due to high demand.",
        }]
        expected = build_output_row(row, notes)
        actual = dict(expected)
        actual["matched_note_id"] = "N002"
        actual["reason"] = (
            "Matches note N002 dated 2025-01-20: A regional festival week saw a temporary surcharge. "
            "Evidence quote: A regional festival week saw a temporary surcharge"
        )
        self.assertTrue(_report_matches_calculation([actual], [expected], notes))


if __name__ == "__main__":
    unittest.main()
