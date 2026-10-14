import unittest
from datetime import date
from decimal import Decimal

from src.cost_calculator import calculate_weekly_rates, monday_of


class CostCalculatorTests(unittest.TestCase):
    def test_weighted_cost_rate_and_monday_week_boundary(self):
        records = [
            {"origin": "A", "destination": "B", "route_type": "Short", "shipment_date": "2024-01-07",
             "quantity_tonnes": "2", "distance_km": "10", "freight_cost_inr": "100", "shipment_id": "1"},
            {"origin": "A", "destination": "B", "route_type": "Short", "shipment_date": "2024-01-06",
             "quantity_tonnes": "1", "distance_km": "10", "freight_cost_inr": "100", "shipment_id": "2"},
            {"origin": "A", "destination": "B", "route_type": "Short", "shipment_date": "2024-01-08",
             "quantity_tonnes": "1", "distance_km": "10", "freight_cost_inr": "100", "shipment_id": "3"},
        ]
        weekly = calculate_weekly_rates(records)
        self.assertEqual(len(weekly), 2)
        self.assertEqual(weekly[0]["week"], date(2024, 1, 1))
        self.assertEqual(weekly[1]["week"], date(2024, 1, 8))
        self.assertEqual(weekly[0]["rate"], Decimal(200) / Decimal(30))
        self.assertEqual(weekly[1]["rate"], Decimal(10))
        self.assertEqual(monday_of("2024-01-07"), date(2024, 1, 1))

    def test_invalid_measure_rejected(self):
        row = {"origin": "A", "destination": "B", "route_type": "Short", "shipment_date": "2024-01-01",
               "quantity_tonnes": "0", "distance_km": "10", "freight_cost_inr": "1", "shipment_id": "bad"}
        with self.assertRaises(ValueError):
            calculate_weekly_rates([row])

    def test_grouping_keeps_route_type_and_week_separate_and_is_weighted(self):
        rows = [
            {"origin": "A", "destination": "B", "route_type": "Short", "shipment_date": "2024-01-01",
             "quantity_tonnes": "1", "distance_km": "10", "freight_cost_inr": "100", "shipment_id": "1"},
            {"origin": "A", "destination": "B", "route_type": "Short", "shipment_date": "2024-01-07",
             "quantity_tonnes": "2", "distance_km": "10", "freight_cost_inr": "100", "shipment_id": "2"},
            {"origin": "A", "destination": "B", "route_type": "Long", "shipment_date": "2024-01-07",
             "quantity_tonnes": "1", "distance_km": "10", "freight_cost_inr": "50", "shipment_id": "3"},
            {"origin": "C", "destination": "D", "route_type": "Short", "shipment_date": "2024-01-07",
             "quantity_tonnes": "1", "distance_km": "20", "freight_cost_inr": "40", "shipment_id": "4"},
            {"origin": "A", "destination": "B", "route_type": "Short", "shipment_date": "2024-01-08",
             "quantity_tonnes": "1", "distance_km": "10", "freight_cost_inr": "100", "shipment_id": "5"},
        ]
        result = {(r["origin"], r["destination"], r["route_type"], r["week"]): r["rate"]
                  for r in calculate_weekly_rates(rows)}
        self.assertEqual(len(result), 4)
        self.assertEqual(result[("A", "B", "Short", date(2024, 1, 1))], Decimal(200) / Decimal(30))
        self.assertEqual(result[("A", "B", "Long", date(2024, 1, 1))], Decimal(5))
        self.assertEqual(result[("C", "D", "Short", date(2024, 1, 1))], Decimal(2))
        self.assertEqual(result[("A", "B", "Short", date(2024, 1, 8))], Decimal(10))


if __name__ == "__main__":
    unittest.main()
