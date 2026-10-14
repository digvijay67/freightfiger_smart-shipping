import unittest
from datetime import date, timedelta
from decimal import Decimal

from src.anomaly_detector import enrich_with_baselines, is_increase_anomaly


def rate(route, week, value, route_type="Short"):
    origin, destination = route.split("-")
    return {"origin": origin, "destination": destination, "route": route,
            "route_type": route_type, "week": week, "rate": Decimal(value)}


class AnomalyDetectorTests(unittest.TestCase):
    def test_previous_eight_available_rates_excludes_current_and_no_padding(self):
        start = date(2024, 1, 1)
        weekly = [rate("A-B", start + timedelta(days=7*i), str(i+1)) for i in range(10)]
        rows = enrich_with_baselines(weekly)
        self.assertIsNone(rows[0]["own_baseline"])
        self.assertEqual(rows[3]["own_weeks"], 3)
        self.assertEqual(rows[3]["own_baseline"], Decimal(2))
        self.assertEqual(rows[9]["own_weeks"], 8)
        self.assertEqual(rows[9]["own_baseline"], Decimal("5.5"))

    def test_missing_calendar_weeks_are_not_padded(self):
        weekly = [rate("A-B", date(2024, 1, 1), "2"),
                  rate("A-B", date(2024, 1, 15), "4"),
                  rate("A-B", date(2024, 2, 5), "8")]
        current = enrich_with_baselines(weekly)[-1]
        self.assertEqual(current["own_weeks"], 2)
        self.assertEqual(current["own_baseline"], Decimal(3))

    def test_baseline_uses_last_eight_of_more_than_eight_and_not_future_rows(self):
        start = date(2024, 1, 1)
        weekly = [rate("A-B", start + timedelta(days=7*i), str(i+1)) for i in range(11)]
        current = enrich_with_baselines(weekly)[10]
        self.assertEqual(current["own_weeks"], 8)
        self.assertEqual(current["own_baseline"], Decimal("6.5"))
        early = enrich_with_baselines([weekly[0], weekly[1], weekly[10]])[0]
        self.assertIsNone(early["own_baseline"])

    def test_peer_baseline_is_mean_of_other_same_type_route_rates(self):
        week = date(2024, 1, 1)
        rows = enrich_with_baselines([rate("A-B", week, "2"), rate("C-D", week, "4"),
                                      rate("E-F", week, "6", "Long")])
        self.assertEqual(rows[0]["peer_baseline"], Decimal(4))
        self.assertEqual(rows[2]["peer_baseline"], None)

    def test_peer_scope_excludes_current_route_week_and_other_types(self):
        week = date(2024, 1, 1)
        rows = enrich_with_baselines([
            rate("A-B", week, "2", "Short"), rate("C-D", week, "4", "Short"),
            rate("E-F", week, "100", "Long"), rate("G-H", date(2024, 1, 8), "200", "Short"),
        ])
        self.assertEqual(rows[0]["peer_baseline"], Decimal(4))
        self.assertEqual(rows[0]["peer_routes"], 1)

    def test_threshold_strictly_greater(self):
        row = {"rate": Decimal("12.01"), "own_baseline": Decimal(10), "peer_baseline": None}
        self.assertTrue(is_increase_anomaly(row, Decimal(20)))
        row["rate"] = Decimal(12)
        self.assertFalse(is_increase_anomaly(row, Decimal(20)))

    def test_or_rule_peer_only_and_no_comparable_baseline(self):
        row = {"rate": Decimal(130), "own_baseline": Decimal(200), "peer_baseline": Decimal(100)}
        self.assertTrue(is_increase_anomaly(row, Decimal(20)))
        row = {"rate": Decimal(130), "own_baseline": None, "peer_baseline": None}
        self.assertFalse(is_increase_anomaly(row, Decimal(20)))

    def test_zero_baseline_has_no_defined_percentage_increase(self):
        row = {"rate": Decimal(10), "own_baseline": Decimal(0), "peer_baseline": None}
        self.assertFalse(is_increase_anomaly(row, Decimal(20)))


if __name__ == "__main__":
    unittest.main()
