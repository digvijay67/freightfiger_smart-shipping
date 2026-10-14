import unittest

from src.evaluation import _load_cases, evaluate_cases


class EvaluationHarnessTests(unittest.TestCase):
    def test_labeled_cases_cover_required_scenarios(self):
        cases = _load_cases()
        self.assertEqual(len(cases), 4)
        self.assertEqual(
            {case["expected_verdict"] for case in cases},
            {"justified", "unexplained", "not_anomaly"},
        )
        self.assertIn("N001;N009", {case["source_note_ids_reviewed"] for case in cases})

    def test_evaluation_cases_match_current_source_data_and_notes(self):
        results, _ = evaluate_cases()
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result["passed"] for result in results), results)


if __name__ == "__main__":
    unittest.main()
