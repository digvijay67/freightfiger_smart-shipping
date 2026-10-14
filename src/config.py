"""Central paths and configurable anomaly threshold."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
EVIDENCE_DIR = ROOT / "evidence"
SHIPMENTS_FILE = DATA_DIR / "shipment_records.csv"
NOTES_FILE = DATA_DIR / "context_notes.csv"
SAMPLE_OUTPUT_FILE = DATA_DIR / "sample_output_format_v2.csv"
REPORT_FILE = OUTPUT_DIR / "anomaly_report.csv"
REPRODUCIBILITY_FILE = EVIDENCE_DIR / "reproducibility_check.txt"
TOKEN_LOG_FILE = EVIDENCE_DIR / "token_cost_log.md"
WEEKLY_HISTORY = 8
# Deliberate default: brief provides no threshold. Override with
# ANOMALY_THRESHOLD_PCT (e.g. 20 means an increase strictly above 20%).
ANOMALY_THRESHOLD_PCT = os.getenv("ANOMALY_THRESHOLD_PCT", "20")
OUTPUT_COLUMNS = [
    "route", "week_of", "cost_per_tonne_km", "vs_own_history",
    "vs_similar_routes", "flagged", "matched_note_id", "reason",
]
