# Freight Tiger Smart Shipping Cost Assistant

Weekly cost analysis and anomaly reporting for the supplied shipment CSVs. Calculations and anomaly flags remain deterministic. By default, note matching and explanations also use the existing deterministic rules. An optional local Ollama RAG path can semantically rank already route/date/evidence-eligible notes and generate a short explanation; it never decides a numeric flag or creates a note ID.

## Files and input schema

- `data/shipment_records.csv` (2,940 rows): `shipment_id, origin, destination, route_type, material, quantity_tonnes, distance_km, freight_cost_inr, shipment_date, transporter`.
- `data/context_notes.csv` (10 notes): `note_id, date, applies_to, note`.
- `data/sample_output_format_v2.csv`: the output contract, in this exact order: `route, week_of, cost_per_tonne_km, vs_own_history, vs_similar_routes, flagged, matched_note_id, reason`.

The sample CSV stores every field as text. The report emits the rate as a two-decimal numeric string; week as ISO Monday date; percentages and verdicts as text; and an empty string for a missing note ID. It contains unusual increase rows only. `Yes` means unexplained and review-worthy; `No (justified)` means an anomaly with an applicable supporting note.

## Setup (Windows / VS Code)

Requires Python 3.10 or newer. The application and evaluation harness use only the Python standard library.

1. Open this folder in VS Code and select a Python 3.10+ interpreter. The project has no third-party Python dependencies.
2. If `.venv` already exists, activate and verify it; do not recreate it blindly. Create a virtual environment only when one is not already present:

   ```powershell
   if (-not (Test-Path .venv)) { py -m venv .venv }
   .\.venv\Scripts\Activate.ps1
   python --version
   ```

3. Select `.venv` using **Python: Select Interpreter** in the Command Palette. No package installation is required.
4. Run the evaluation and tests; run the pipeline when you want to regenerate its output files:

   ```powershell
   python -m src.evaluation
   python -m unittest discover -s tests -v
   python -m src.main
   ```

No third-party package is required. Set the threshold on a run with `python -m src.main --threshold-pct 20`, or set `$env:ANOMALY_THRESHOLD_PCT = "20"` in PowerShell before running. Comparisons use strict `>`.

The assessment brief does not specify an anomaly threshold. The configurable 20% default is an explicitly disclosed implementation assumption; comparisons use strict `>`.

## Ask questions about the current results

First generate or refresh the report, then start the interactive terminal assistant:

```powershell
python -m src.main
python -m src.main --chat
```

You can ask multiple questions in one session. Type `exit`, `quit`, or `q` to leave. For example:

- `Which routes have unusual shipping costs?`
- `Why was Ahmedabad-Mumbai flagged on 2025-01-20?`
- `Tell me more about Mumbai-Pune for the week of 2025-12-22.`
- `Explain the Mumbai-Pune anomaly from 2025-12-22.`
- `Show details for Mumbai-Pune on 2025-12-22.`
- `Tell me more about the last anomaly.` (the final row in the report's current order)
- `Show me three representative anomalies.`
- `Which anomalies have supporting context notes?`
- `Which anomalies have no supporting evidence?`
- `What is the difference between historical and peer baselines?`
- `What are the historical and peer baselines for Mumbai-Pune?`
- `Which route had the largest cost-per-tonne-km increase?`
- `Which route had the largest increase versus its historical baseline?`
- `Which route had the largest increase versus its peer baseline?`
- `Summarize the findings for a non-technical audience.`

Without a route name, a baseline question explains both definitions: own-history uses up to eight strictly earlier available weekly rates, while peers use all other routes of the same `route_type` in the same week. A route-specific baseline question returns that route's calculated baselines. A generic largest-increase question reports two separate rankings, one versus the own-history baseline and one versus the same-week peer baseline; wording that names one baseline returns only that comparison. Each percentage is calculated from that baseline independently and rounded to one decimal place with the report's half-up rule. Unknown route names return a no-match answer.

This is a deterministic question router, not an LLM. At startup it checks the report against a fresh calculation, the configured threshold, and the input hashes recorded by the last pipeline run. If any differ, it refuses to answer and asks you to run `python -m src.main`. It also checks input hashes before every answer and ends the session if a source file changes. Explanations quote only the matched context note and identify it by note ID; a note is supporting context, not proof of causation. Three-example requests select up to three real rows from the full report; the report itself still retains every detected anomaly. Chat responses are not persisted or cached. The Q&A assistant itself does not call Ollama; optional RAG applies only while building report explanations.

## Optional local Ollama RAG

For an optional, Windows-focused Ollama setup guide, including a download-only installer helper and model recommendations, see [docs/ollama_setup.md](docs/ollama_setup.md).

The default setup needs no third-party packages and makes no Ollama calls. To explicitly use deterministic mode in PowerShell, clear the model variables before running the report:

```powershell
$env:OLLAMA_CHAT_MODEL = ''
$env:OLLAMA_EMBED_MODEL = ''
python -m src.evaluation
python -m unittest discover -s tests -v
python -m src.main
```

The final command regenerates `output/anomaly_report.csv`, `output/run_1.csv` through `run_3.csv`, and the reproducibility and token logs. Omit it when you need to preserve those existing files.

To enable optional local RAG, install and start Ollama yourself, verify `ollama list`, and configure only models that are already installed. The program never downloads models automatically. The local pair validated for this project is `qwen3:0.6b` for chat and `nomic-embed-text:latest` for embeddings. In PowerShell:

```powershell
$env:OLLAMA_EMBED_MODEL = "nomic-embed-text:latest"
$env:OLLAMA_CHAT_MODEL = "qwen3:0.6b"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_TIMEOUT_SECONDS = "8"
$env:RAG_TOP_K = "3"
$env:RAG_MIN_SIMILARITY = "0.15"
$env:OLLAMA_SEED = "42"
python -m src.main
```

`src/local_rag.py` uses Ollama's local embedding and chat endpoints and an in-memory cosine-similarity vector index; the index is rebuilt in each fresh worker process and is not a persistent database. The project uses this lightweight in-memory index and the Python standard library; it does not add ChromaDB or another vector-store dependency. For each anomalous route-week, deterministic exact-route/`All Routes`, date-window, and positive/negative evidence rules run first. Only eligible supporting notes enter vector ranking and the model prompt. The model must return an eligible note ID, an exact quote from that note, and an explanation whose content words are present in the evidence; invalid results fall back to the existing deterministic explanation. A note explicitly saying costs were unaffected, a wrong-route note, or a wrong-date note cannot justify an anomaly.

If no eligible note exists, the row remains unexplained (`flagged=Yes`, blank `matched_note_id`) and no model call is made. If a model is not configured or an Ollama request, timeout, embedding, or response validation fails, the pipeline uses the existing deterministic matcher when a supporting note exists; otherwise the row remains unexplained. Diagnostic codes and details distinguish those conditions without changing the CSV schema. `evidence/token_cost_log.md` is the historical deterministic-only zero-call run log; actual live-model usage is recorded separately in `evidence/live_rag_validation.md` and `evidence/live_rag_usage.json`. The JSON records `ollama_chat_calls`, `ollama_embedding_calls`, `input_tokens`, `output_tokens`, `embedding_tokens`, and `embedding_tokens_reported`. The recorded local run had no hosted API charge; electricity and hardware costs are excluded, and no published-rate estimate is claimed for local inference. A seeded temperature-zero request helps repeatability, but this project has only one validated live-RAG report run; three-run RAG reproducibility has **not** been established with Ollama enabled.

The separate `output/live_rag_trial.csv` preserves one live-RAG execution without replacing the regular report. `evidence/live_rag_validation.md` and `evidence/live_rag_usage.json` describe that single execution; live-RAG reproducibility is not verified. `evidence/submission_validation.md` is the earlier 56-test deterministic validation snapshot with three-process reproducibility and input hashes. `evidence/qa_update_validation.md` records an earlier 59-test Q&A update check and 4/4 evaluation; it predates the latest causal-question Q&A changes. The current verification limits and next steps are in `evidence/current_submission_status.md`. `evidence/final_assessment_audit.md` is a historical, limited pre-RAG audit and does not certify full current rubric compliance.

For a route-specific detail question, include one route and an ISO date or Monday week. If the route has multiple anomaly weeks and no date is supplied, the assistant asks which week you mean. A route/date with no anomaly row returns a no-match answer. `last anomaly` means the final row in the current report order; it does not refer to the last question in the chat.

## Algorithm and assumptions

1. Parse numeric shipment fields as `Decimal`; reject invalid/non-finite values, non-positive quantity/distance, and negative freight cost.
2. Group by exact `origin`, `destination`, existing `route_type`, and Monday-based week. For each group calculate `sum(freight_cost_inr) / sum(quantity_tonnes * distance_km)`.
3. For each route-week, own-history baseline is the arithmetic mean of up to the eight most recent available earlier weekly route rates. The current week is excluded and missing weeks are not padded. If fewer than eight exist, use all available; if none, baseline is unavailable.
4. Peer baseline is the arithmetic mean of the other route-week rates with the same `route_type` and week. The current route is excluded; peers are equally weighted at the route-rate level.
5. A row is an anomaly if it is strictly above either available baseline by more than the configured threshold. The brief says to compare against own history "or" similar routes; the implementation applies that as an either-baseline rule. The numeric 20% default and strict `>` cutoff are implementation assumptions because the brief gives no numeric cutoff. With no available baseline, there is no comparison for that baseline.
6. Retrieve a note only when its `applies_to` exactly matches the route (case-insensitive) or says `All Routes`, its validity overlaps the shipment week, and its text explicitly supports increased costs (for example, surcharge or higher trip costs). A dated note applies only during its Monday-based week unless it explicitly names a date interval; N001's stated Feb 24–Mar 8 range is honored. Negative/no-change notes and notes about irrelevant routes are excluded. Unmatched/insufficient notes leave `matched_note_id` blank and the reason says unexplained.

Input headers and order are checked against the supplied schemas; duplicate headers, malformed row widths, and blank required cells fail fast. Shipment and note IDs are source fields; the pipeline does not synthesize records. The column names imply tonnes and kilometres, and the formula treats them as such; the supplied files do not include a separate unit dictionary to verify those units independently. There is no database or automatic ingestion service: each invocation reads the supplied static CSV files from `data/`.

Numeric flags are decided before note retrieval. Notes can label the reason for an already-detected increase but cannot change the rate, baseline, or anomaly decision. The sample's `similar-length routes` phrase is interpreted using the requested same-`route_type` peer rule.

## Evaluation and reproducibility

`python -m src.evaluation` runs a small deterministic labeled check against the current shipment and note CSVs. Its four manually reviewed cases cover a note-supported anomaly (N002), an unexplained anomaly, a non-anomaly, and an anomaly where nearby notes are outside the applicable date window (N001 ends Mar 8; N009 begins in the week of Mar 17). The expected labels and the calculation/note-date rationale are in `data/evaluation_cases.csv`. It reports case count, pass/fail totals, pass rate, and field-level mismatch details, and exits nonzero if any case fails. The labels were manually checked against the source rows and notes at the documented 20% default threshold; if `ANOMALY_THRESHOLD_PCT` is overridden, cases whose expected flags change should fail visibly and the report names the active threshold. The harness reads source data and the sample schema and does not write or overwrite production outputs.

Reference result for the supplied inputs at the default 20% threshold: **4 cases, 4 passed, 0 failed (100.0%)**. The result is recomputed on every run; use the command output as the current result if input CSVs or the threshold change.

`tests/` contains `unittest` checks for weighted rate aggregation, Monday boundaries, invalid measures, the previous-eight available baseline, peer exclusions, strict threshold boundary, note route/date scope, explicit all-route evidence, blank ID on unsupported claims, exact output schema, deterministic CSV writing, and the labeled evaluation harness. The four-case labeled set is a small behavioral check, not a statistically representative anomaly-accuracy benchmark.

`python -m src.main` launches three separate Python processes. Each process reloads the original input CSVs and writes one of `output/run_1.csv`, `run_2.csv`, `run_3.csv`; the parent verifies the input hashes stayed unchanged and the output SHA-256 hashes match, then writes `output/anomaly_report.csv`. It records before/after input hashes, output hashes, and the runtime version in `evidence/reproducibility_check.txt`. It aggregates actual Ollama request counts and chat token usage reported by each worker into `evidence/token_cost_log.md`, including fallback diagnostics. When Ollama is not configured or reachable, the deterministic path records zero successful model usage and the relevant fallback reason. The checked-in reproducibility and token logs describe the last completed run before the optional RAG integration; regenerate them only after running the updated pipeline and verifying it.

On a successful standard invocation, the report, three run files, and evidence files are replaced; candidate run files are staged and are not committed if hashes differ or source inputs changed. Run files are separate paths for comparison, but are not historical archives. The test suite covers aggregation and Monday boundaries, input validation, history and peer baselines, threshold/OR behavior, note route/date/evidence rules, output schema, reproducibility, supported Q&A intents, ambiguous or unsupported questions, stale-result protection, and mocked Ollama/RAG validation and fallback behavior. The separate four-case labeled evaluation checks selected source-backed outcomes; it does not replace the broader unit tests or establish statistical accuracy across all routes and weeks.

## Limitations

- The 20% default and strict `>` cutoff are documented implementation assumptions, not values specified by the brief. The either-baseline logic follows the brief's "own history or similar routes" wording. Tune and disclose the cutoff for a production policy.
- Averages are unweighted across the prior weekly route rates and across peers, as specified; small peer counts can be noisy.
- Notes lack structured end dates and impact fields. The conservative rule uses the note date's week unless an explicit interval is written, so longer-lived effects may not be credited.
- Output schema has no baseline columns or sample count, limiting audit detail in the CSV; calculations remain visible in code and can be extended if the contract changes.
- Deterministic route/date/evidence checks remain the authority for whether a note can support an anomaly. Optional local semantic retrieval can rank only those eligible notes; it can miss valid notes, and lexical output validation is a conservative guard rather than a formal proof of entailment. Review matched notes before operational use.
- Q&A supports a documented set of question patterns and route names from the current source data. It does not interpret arbitrary questions, accept alternate natural-language date formats for precise filtering, or retain conversation history between sessions.
