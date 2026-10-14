import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from src.config import ROOT, SHIPMENTS_FILE, NOTES_FILE
from src.report_writer import sha256_file


class FreshProcessReproducibilityTests(unittest.TestCase):
    def test_three_fresh_processes_reuse_unchanged_original_inputs(self):
        input_hashes_before = (sha256_file(SHIPMENTS_FILE), sha256_file(NOTES_FILE))
        output_hashes = []
        with patch.dict(os.environ, {"OLLAMA_EMBED_MODEL": "", "OLLAMA_CHAT_MODEL": ""}):
            with tempfile.TemporaryDirectory() as temp:
                for number in range(1, 4):
                    filename = f"run_{number}.csv"
                    subprocess.run(
                        [sys.executable, "-m", "src.main", "--threshold-pct", "20",
                         "--_worker-output", filename, "--_worker-dir", temp],
                        cwd=ROOT, check=True, capture_output=True, text=True,
                    )
                    output_hashes.append(sha256_file(Path(temp) / filename))
        input_hashes_after = (sha256_file(SHIPMENTS_FILE), sha256_file(NOTES_FILE))
        self.assertEqual(input_hashes_after, input_hashes_before)
        self.assertEqual(len(set(output_hashes)), 1)


if __name__ == "__main__":
    unittest.main()
