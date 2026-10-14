"""CSV loading with explicit header and row-shape validation."""
import csv
from pathlib import Path


def load_csv(
    path: Path,
    required_columns: set[str] | None = None,
    *,
    expected_columns: list[str] | None = None,
    nonempty_columns: set[str] | None = None,
) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        if headers is None:
            raise ValueError(f"CSV has no header: {path}")
        if len(headers) != len(set(headers)):
            raise ValueError(f"{path.name} contains duplicate column names")
        if expected_columns is not None and headers != expected_columns:
            raise ValueError(f"{path.name} headers/order differ from expected schema")
        missing = (required_columns or set()) - set(headers)
        if missing:
            raise ValueError(f"{path.name} missing columns: {', '.join(sorted(missing))}")

        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"{path.name}:{line_number} has more fields than its header")
            if any(value is None for value in row.values()):
                raise ValueError(f"{path.name}:{line_number} has fewer fields than its header")
            for column in nonempty_columns or set():
                if not row.get(column, "").strip():
                    raise ValueError(f"{path.name}:{line_number} has blank required field {column!r}")
            rows.append(row)
        return rows
