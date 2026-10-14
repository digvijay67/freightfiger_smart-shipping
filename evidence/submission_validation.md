# Final submission validation

**Run date:** 2026-10-14  
**Python:** 3.12.10, existing `.venv`  
**Scope:** Tests, evaluation, deterministic three-process reproducibility, schema, and input preservation. Production report/evidence files were not regenerated.

## Automated checks

With `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBED_MODEL` empty and `PYTHONDONTWRITEBYTECODE=1`, the following were run:

```powershell
& '.\.venv\Scripts\python.exe' -B -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' -B -m src.evaluation
```

Results: **56 tests passed, 0 failed**, with no skips reported; evaluation: **4 cases passed, 0 failed (100%)**.

## Fresh deterministic processes

With Ollama model variables empty and threshold `20`, three separate processes invoked the internal worker entry point:

```powershell
& '.\.venv\Scripts\python.exe' -B -m src.main --threshold-pct 20 --_worker-output run_1.csv --_worker-dir $stage
& '.\.venv\Scripts\python.exe' -B -m src.main --threshold-pct 20 --_worker-output run_2.csv --_worker-dir $stage
& '.\.venv\Scripts\python.exe' -B -m src.main --threshold-pct 20 --_worker-output run_3.csv --_worker-dir $stage
```

`$stage` was a fresh OS temporary directory. All three exited 0, each had 20 rows and the exact sample header:

`route,week_of,cost_per_tonne_km,vs_own_history,vs_similar_routes,flagged,matched_note_id,reason`

Each staged output SHA-256 was `BAC900D7B03A2B871282627625B5DBA4A44F2B5D4C167D874976B6C160C9F403`; they were byte-identical. Shipment input SHA-256 before/after was `1A2B4D66C4DC694111BA37B966486B5B0650DF9EC8687402F3434117B140F4B6`; context-note input SHA-256 before/after was `875C57A896AC3DFAC0F712F8865B287BB5D2BD5423D26E798297B74DCE87E6DC`.

The existing deterministic report, `run_1.csv` through `run_3.csv`, `evidence/reproducibility_check.txt`, and `evidence/token_cost_log.md` were not overwritten. The separate model-enabled trial and its measured usage are recorded in `output/live_rag_trial.csv`, `evidence/live_rag_validation.md`, and `evidence/live_rag_usage.json`.

## Assessment and reproducibility limitations

Live RAG was exercised separately with the local `qwen3:0.6b` and `nomic-embed-text:latest` models. It produced two validated grounded explanations and safely fell back for one invalid generated explanation. It was run once only; model-enabled byte-identical reproducibility has not been tested. The unit tests' model calls are mocked and the labeled evaluation checks deterministic outcomes, not model quality.

The supplied assessment PDF exists, but the prior audit found its embedded character map corrupts important peer, AI/RAG, and evaluation wording. No PDF text-extraction or render utilities/libraries are installed in this project environment. Therefore, this package does not claim full PDF-rubric compliance for those obscured clauses.

The original verified submission ZIP remains separate and unchanged. This submission package is a new archive; it excludes `.venv`, model weights, caches, secrets, and temporary run directories.
