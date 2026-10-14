# Local Ollama RAG validation record

**Run date:** 2026-10-14  
**Project:** `C:\Users\digvi\freighttiger-smart-shipping`  
**Purpose:** Record one actual local-model pipeline run separately from mocked unit tests, deterministic fallback checks, and the historical token log.

## Models and direct endpoint checks

- Ollama: `0.34.0`, local API at `http://127.0.0.1:11434`.
- Chat model configured: `qwen3:0.6b` (model ID `7df6b6e09427`, listed size 522 MB).
- Embedding model configured: `nomic-embed-text`; installed tag shown by Ollama: `nomic-embed-text:latest` (model ID `0a109f422b47`, 274 MB).
- Direct chat smoke check: `POST /api/chat` with a prompt to reply exactly `READY`; model returned `READY.`
- Direct embedding smoke check: `POST /api/embed` returned a nonempty **768-dimensional** vector.

The direct smoke calls are separate from the per-worker usage totals below. Their token counts were not recorded by the smoke-check command and are not included in the worker totals.

## Actual RAG pipeline run

One fresh worker process ran with `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_CHAT_MODEL=qwen3:0.6b`, `OLLAMA_EMBED_MODEL=nomic-embed-text`, `OLLAMA_TIMEOUT_SECONDS=60`, `RAG_TOP_K=3`, `RAG_MIN_SIMILARITY=0.15`, `OLLAMA_SEED=42`, and threshold 20%. It wrote first to a temporary directory; the preserved copy is `output/live_rag_trial.csv` and the raw usage record is `evidence/live_rag_usage.json`.

Worker-reported local API usage:

- Chat calls: **3**.
- Embedding calls: **3**.
- Chat input tokens: **485**.
- Chat output tokens: **1,145**.
- Embedding tokens: **133** (reported by the embedding endpoint).
- Hosted API cost: **$0.00**. Local electricity and hardware costs are not measured.

Results and safeguards:

- **2 `rag_grounded_success` explanations:** Chennai-Bangalore, weeks 2025-02-24 and 2025-03-03, both cite eligible note `N001`.
- **1 safe response-validation fallback:** Ahmedabad-Mumbai, week 2025-01-20. The model output contained date tokens `01`, `20`, and `2025` that were absent from the evidence text; validation rejected the generated wording and the existing deterministic matcher retained eligible note `N002`.
- **17 unexplained anomalies:** no eligible supporting note, no model request, and blank `matched_note_id`.
- All three justified row note IDs were checked against the deterministic route/date/evidence eligibility function. The CSV schema is the exact eight-column sample schema, has 20 rows, and has the same numeric rate/baseline fields and anomaly flags as the checked-in deterministic report.

Hashes for the preserved trial artifacts:

- `output/live_rag_trial.csv`: `F5F7A994F2F89086FE0207F45FA2A26D6C23B3C59C8FE9782643B97DEC6547F8`
- `evidence/live_rag_usage.json`: `48BF3F580FD438F0688D3DCB2F675EE3B8821331F40AA9220DEC145F6C93AA01`

## Separate deterministic fallback and tests

A separate worker was configured with the model names but an intentionally unavailable base URL, `http://127.0.0.1:11435`, and a one-second timeout. It recorded three embedding-request failures and 17 `unexplained_no_eligible_note` outcomes, made zero chat calls, and fell back to the deterministic matcher. Its report SHA-256 was `BAC900D7B03A2B871282627625B5DBA4A44F2B5D4C167D874976B6C160C9F403`, byte-identical to the checked-in deterministic report.

After the live run, the full `unittest` suite was run with both model environment variables empty: **56 tests passed, 0 failed**. This includes mocked tests for invalid/unsupported model output and unaffected-cost notes; these tests do not themselves call the local models. The deterministic evaluation returned **4/4 cases passed (100%)** and likewise does not score generated model prose.

## Scope and limitations

- This is **one** live-RAG pipeline run, not three model-enabled runs. Live-RAG byte-identical reproducibility is **not established**.
- One of three chat outputs was correctly rejected and fell back; the 0.6B chat model did not produce accepted grounded text for every eligible note.
- The 56-test suite exercises RAG validation and fallback with mocks, while the four-case evaluation checks deterministic labels. Neither is a statistical benchmark of model explanation quality.
- The existing `evidence/token_cost_log.md` remains the prior deterministic-only run record (zero calls); it was not overwritten. This file and its JSON companion record actual live usage.
- The original assessment PDF's extracted character map obscures portions of the peer, AI, and evaluation rubric. See the prior assessment audit; full PDF-specific compliance remains unverified.
