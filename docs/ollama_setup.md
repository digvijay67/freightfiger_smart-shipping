# Optional local Ollama setup (Windows)

The FreightTiger report and Q&A fallback work without Ollama. Ollama is optional; model use affects only grounded note ranking and explanation text. Do not run the production pipeline while protecting checked-in outputs: `python -m src.main` replaces `output/anomaly_report.csv`, all three `output/run_*.csv` files, and the reproducibility and token logs.

## What this PC reported

At the time of this check, the machine reported 15.35 GB total RAM and 1.46 GB free RAM, an NVIDIA GeForce GTX 1650 with 4 GB reported VRAM, AMD Radeon integrated graphics, and 13.04 GB free on C:. Free RAM and disk space change over time. The small chat model below is a cautious starting point; GPU use and inference speed depend on the local Ollama driver/runtime.

## Recommended small model pair

Recommended starting pair:

- Chat: `qwen3:0.6b` — approximately 523 MB download.
- Embeddings: `nomic-embed-text` — approximately 274 MB download.
- Combined model downloads: approximately 797 MB, plus temporary download/cache overhead.

These are distinct model roles: Qwen3 generates a constrained explanation, while `nomic-embed-text` returns note embeddings. The current disk reading leaves room for this pair, but the low free system RAM may constrain performance. Model sizes are registry estimates and can change. The Ollama library lists Qwen3 0.6B at about 523 MB and the embedding model at 274 MB. See [Qwen3 in Ollama](https://ollama.com/library/qwen3) and [nomic-embed-text in Ollama](https://ollama.com/library/nomic-embed-text).

The model names above are approved for this setup. Do not run either `ollama pull` command until Ollama is installed, its local API responds, and you explicitly approve the pull commands in this setup session.

## Download and install Ollama

1. Open PowerShell in the project directory.
2. Run the helper. It prompts before downloading, fetches only from Ollama's official Windows download link, refuses to overwrite a previous installer, verifies its Windows signature, and **does not install or launch it**:

   ```powershell
   .\scripts\prepare_ollama_installer.ps1
   ```

3. Review the output and installer in your Downloads folder. To install, launch `OllamaSetup.exe` yourself and respond to Windows security/UAC prompts. The installer is separate from this project script.
4. Launch Ollama from the Windows Start menu. In a new PowerShell window, verify:

   ```powershell
   ollama --version
   Invoke-RestMethod http://127.0.0.1:11434/api/tags
   ```

If the command is not found in an already-open terminal after installation, open a new PowerShell window and retry. Do not use the `irm ... | iex` installer command: this project uses a downloaded installer that you can inspect and launch manually.

## Download models only after approving their names

After approval, run these commands individually and allow each model download to finish:

```powershell
ollama pull qwen3:0.6b
ollama pull nomic-embed-text
ollama list
```

Verify the chat endpoint with an actual local response:

```powershell
ollama run qwen3:0.6b
```

Enter a short prompt such as `Reply with the word ready`, confirm a response, then type `/bye`.

Verify the embedding endpoint:

```powershell
$body = @{ model = 'nomic-embed-text'; input = 'Freight cost context note' } | ConvertTo-Json
$result = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/embed' -ContentType 'application/json' -Body $body
"Embedding dimensions: $($result.embeddings[0].Count)"
```

Both commands must succeed before calling the setup live-RAG verified.

## Configure the project

In the PowerShell window where you will run the project:

```powershell
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
$env:OLLAMA_CHAT_MODEL = 'qwen3:0.6b'
$env:OLLAMA_EMBED_MODEL = 'nomic-embed-text'
$env:OLLAMA_TIMEOUT_SECONDS = '30'
$env:RAG_TOP_K = '3'
$env:RAG_MIN_SIMILARITY = '0.15'
$env:OLLAMA_SEED = '42'
```

These values last only for that PowerShell session. Clear the two model variables to use deterministic fallback again:

```powershell
$env:OLLAMA_CHAT_MODEL = ''
$env:OLLAMA_EMBED_MODEL = ''
```

## Safe integration check without overwriting project outputs

Once both models are installed and their direct checks succeed, run one fresh pipeline worker into a temporary directory. It reads the original shipment and context-note CSVs but writes the trial report and usage record outside the project output/evidence files:

```powershell
$stage = Join-Path $env:TEMP ('freighttiger-rag-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
python -m src.main --threshold-pct 20 --_worker-output run_1.csv --_worker-dir $stage --_worker-usage-file (Join-Path $stage 'usage.json')
Import-Csv (Join-Path $stage 'run_1.csv') | Format-Table route,week_of,flagged,matched_note_id,reason -Wrap
Get-Content (Join-Path $stage 'usage.json')
```

Look for nonzero Ollama embedding/chat call counts and a `rag_grounded_success` diagnostic. A deterministic fallback or zero model calls means the live integration has not been demonstrated. Inspect note IDs and explanations against `data/context_notes.csv`; RAG is allowed to rank only notes that already pass exact route/date and evidence checks. This worker check does not update the checked-in report or logs. Do not run `python -m src.main` afterward unless you intend to regenerate those validated outputs and evidence.

## Security and behavior

- The helper downloads from `https://registry.ollama.com/download/OllamaSetup.exe`, the manual Windows download linked from the official Ollama download page. It requests the literal `DOWNLOAD` confirmation, will not overwrite an existing installer, and validates its Authenticode signature before reporting success.
- The helper never executes an installer, changes PATH, or installs system software. You manually launch the installer and handle Windows prompts.
- Model pulls are separate, explicit commands and are intentionally not automated by the helper.
- If Ollama is absent, stopped, times out, or produces invalid output, the existing deterministic path remains available. Numerical rates, baselines, flags, CSV schema, and note eligibility rules remain deterministic.
