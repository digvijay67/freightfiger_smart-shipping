import tempfile
import unittest
from pathlib import Path

from src.data_loader import load_csv
from src.main import _validate_source_records


class DataLoaderTests(unittest.TestCase):
    def load_text(self, text, **kwargs):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "input.csv"
        path.write_text(text, encoding="utf-8")
        return load_csv(path, **kwargs)

    def test_validates_exact_header_order_and_required_nonempty_cells(self):
        self.assertEqual(self.load_text("id,value\n1,x\n", expected_columns=["id", "value"],
                                        nonempty_columns={"id", "value"}), [{"id": "1", "value": "x"}])
        with self.assertRaises(ValueError):
            self.load_text("value,id\nx,1\n", expected_columns=["id", "value"])
        with self.assertRaises(ValueError):
            self.load_text("id,value\n1,\n", nonempty_columns={"value"})

    def test_rejects_duplicate_headers_and_malformed_row_width(self):
        with self.assertRaises(ValueError):
            self.load_text("id,id\n1,2\n")
        with self.assertRaises(ValueError):
            self.load_text("id,value\n1,x,extra\n")
        with self.assertRaises(ValueError):
            self.load_text("id,value\n1\n")

    def test_source_records_require_unique_ids_and_iso_note_dates(self):
        shipment = {"shipment_id": "S1"}
        note = {"note_id": "N1", "date": "2025-02-24"}
        _validate_source_records([shipment], [note])
        with self.assertRaises(ValueError):
            _validate_source_records([shipment, dict(shipment)], [note])
        with self.assertRaises(ValueError):
            _validate_source_records([shipment], [{"note_id": "N1", "date": "24-02-2025"}])


if __name__ == "__main__":
    unittest.main()
