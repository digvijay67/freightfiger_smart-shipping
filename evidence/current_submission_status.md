# Current submission status

**Recorded:** 2026-10-14

This note describes the project state included in the current submission archive.

## Verification status

- `evidence/qa_update_validation.md` records an earlier run with 59 tests passing and the evaluation harness at 4/4. That run predates the latest causal-question and note-grounding Q&A changes; it does not validate those changes.
- The full test suite and evaluation were attempted again after the latest Q&A edits, but did not start. The existing `.venv` references the missing interpreter `C:\Users\digvi\AppData\Local\Programs\Python\Python312\python.exe`; the launcher lists only Python 2.5. No fresh passing result is claimed for the current code.
- The saved deterministic reproducibility files remain unchanged. The latest Q&A code was not included in a new three-run execution.
- The live-RAG CSV and usage files document one separate local-model execution. Live-RAG reproducibility is **NOT VERIFIED**.

## Data and usage records

The shipment and context-note CSVs, anomaly report, three deterministic run CSVs, and historical token/cost logs are included as existing project artifacts. They were not regenerated while preparing this archive. `evidence/token_cost_log.md` describes a historical deterministic-only run with zero model calls; live local-model usage is reported separately in `evidence/live_rag_validation.md` and `evidence/live_rag_usage.json`.

## Before submission

Restore a compatible Python 3.10+ interpreter, run the documented full test suite and evaluation harness against this code, and refresh validation evidence only after observing the results. Do not claim the saved 59-test result covers later Q&A changes.

The project audit in `evidence/final_assessment_audit.md` is explicitly historical and limited; it does not certify full compliance with every assessment criterion.
