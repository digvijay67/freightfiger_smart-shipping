# Q&A update validation record

**Recorded:** 2026-10-14  
**Scope:** Q&A baseline comparisons and unknown-route fallback after the latest Q&A changes.

In the validation session for the current Q&A implementation, the following commands were executed with Ollama disabled:

```powershell
& '.\.venv\Scripts\python.exe' -B -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' -B -m src.evaluation
```

Observed results:

- Unit tests: **59 passed, 0 failed** (`Ran 59 tests in 1.073s`); no skips were reported.
- Evaluation harness: **4 cases passed, 0 failed (100%)**.
- Ollama chat and embedding model environment variables were empty; this validates deterministic mode only.

This is a saved record of that earlier run, not a fresh run performed during packaging. During the packaging session, the existing `.venv` could not start because its configured Python 3.12.10 executable was missing. Therefore, the test suite and evaluation were **not rerun in the packaging session**. See `evidence/submission_validation.md` for the earlier 56-test validation snapshot and deterministic three-process reproducibility evidence.

This record does not validate live-RAG reproducibility. Live RAG was exercised in a separate single run; three-run RAG reproducibility remains **NOT VERIFIED**.
