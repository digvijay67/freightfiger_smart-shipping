# 10-minute technical walkthrough

## 0:00–1:00 — Inputs and contract

Show the three CSVs and identify the shipment columns, notes fields, and exact eight-column output header. Clarify that the 20% anomaly threshold is a configurable disclosed default because no threshold was supplied.

## 1:00–3:00 — Weekly rate calculation

Walk through `src/cost_calculator.py`: Monday week normalization, four-key grouping, Decimal arithmetic, and `sum(freight_cost_inr) / sum(quantity_tonnes * distance_km)`. Mention input validation.

## 3:00–5:00 — Baselines and flags

Show `src/anomaly_detector.py`: mean of up to eight prior available weekly rates with no current-week leakage; peer mean from other same-type routes in that week. The brief says to compare with own history or similar routes, which the code implements as an either-baseline check. Explain that the 20% default and strict `>` cutoff are assumptions because the brief gives no numeric cutoff.

## 5:00–7:00 — Context and hallucination prevention

Walk through `src/note_retriever.py`, `src/local_rag.py`, and `src/explanation_generator.py`. Route, time overlap, and positive cost evidence are filtered deterministically before semantic retrieval. If Ollama and both configured local models are available, eligible notes are embedded, ranked locally, and passed to the local chat model. Otherwise, or if a response fails validation, the deterministic explanation is used and the fallback is logged. Demonstrate that negative or unrelated notes do not match, and an unsupported increase keeps an empty note ID. Do not claim an actual model run unless Ollama was available and the run log records it.

Use this actual report example: **Ahmedabad-Mumbai, week of 2025-01-20** has a rate of **3.29 INR/tonne-km**, **+29.5%** versus its own-history baseline and **+22.5%** versus same-type peers. It is an increase anomaly, but the report verdict is **No (justified)** because matched note **N002** describes a regional festival-week surcharge on that exact corridor and date. Say that the note supports the explanation but does not prove causation. Then contrast it with an unexplained row, such as Delhi-Jaipur on 2024-11-11, whose `matched_note_id` is blank.

## 7:00–8:30 — Contract and evaluation

The saved validation record `evidence/qa_update_validation.md` reports **59 tests passed, 0 failed** and **4/4 evaluation cases passed** with Ollama disabled, but it predates the latest causal-question Q&A changes. The suite and evaluation were attempted after those edits but could not start because `.venv` points to a missing Python 3.12.10 executable; no fresh pass is claimed for the current code. See `evidence/current_submission_status.md` for this limitation and the next verification step. `evidence/submission_validation.md` contains the earlier 56-test snapshot.

## 8:30–10:00 — Reproducibility and limitations

Three independent deterministic executions completed successfully and produced the same output SHA-256: `BAC900D7B03A2B871282627625B5DBA4A44F2B5D4C167D874976B6C160C9F403`. See `evidence/reproducibility_check.txt` for the saved reproducibility record and input hashes. A separate live-RAG trial was exercised once in a temporary run; **live-RAG reproducibility is NOT VERIFIED**. That single run does not establish repeatability, and no three-run live-RAG comparison was performed.

Keep the usage records distinct: `evidence/token_cost_log.md` is the historical deterministic-only full-run log (zero LLM calls and zero tokens). Actual local-model usage for the separately recorded live-RAG run is in `evidence/live_rag_validation.md` and `evidence/live_rag_usage.json`; the JSON fields include `ollama_chat_calls`, `ollama_embedding_calls`, `input_tokens`, `output_tokens`, `embedding_tokens`, and `embedding_tokens_reported`. The saved live-RAG record reports 3 chat calls, 3 embedding calls, 485 input tokens, 1,145 output tokens, and 133 embedding tokens. A later one-time temporary smoke run was also exercised, but it is not a saved full-run usage record. The recorded local inference has no hosted API charge; electricity and hardware costs are excluded, and no published-rate estimate is claimed for local inference.

Close with the README limitations: the threshold is an assumption, peer means can be noisy, and note end dates are sparse.
