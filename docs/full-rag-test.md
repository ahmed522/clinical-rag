# Full product RAG test

The end-to-end test creates an isolated clinic and exercises the real product
path from account registration through PDF ingestion and final patient answer.
It asks 20 labelled questions and records the answer, evidence, citations,
retrieval/reranking scores, verifier decision, persistence result, and latency.

## 1. Start the API

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Leave this terminal open. Confirm that `http://127.0.0.1:8000/health`
returns `{"status":"ok"}`.

Restart Uvicorn after changing `.env`. A server process that was started with
an old `LLM_MODEL` environment variable keeps that value even when the file is
correct. In PowerShell, clear an old shell override before restarting with:

```powershell
Remove-Item Env:LLM_MODEL -ErrorAction SilentlyContinue
```

## 2. Run the complete 20-question test

Open a second PowerShell terminal in the project root:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_full_rag --allow-external-llm
```

The external-provider confirmation is required because generation and evidence
verification send each question and the retrieved guideline excerpts to the
configured hosted LLM. Do not supply it unless that provider is approved to
process the clinic's source material. It is unnecessary for `mock` and local
`ollama` runs.

The test uses the provider configured in `.env`; it does not force the mock
provider. For a real LLM run, verify that `.env` contains a valid provider and
key, for example:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=your-key
```

The current provider abstraction reads the provider-specific key when
`LLM_API_KEY` is empty. Never commit `.env`.

## 3. Read the result

The terminal prints all 20 questions, full answers, scores, and citations.
Two persistent reports are created in `evaluation/full_rag_runs/`:

- `full_rag_latest.md`: easiest report to read and share.
- `full_rag_latest.json`: full structured results and raw API responses.

Timestamped copies are also preserved so runs can be compared.

The overall gate requires valid/exact citations and verifier approval for every
displayed grounded answer, at least 85% in-scope grounding, 100% abstention on
the three negative cases, correct individualized-dosage refusal, no API errors,
and a complete persisted chat history.

## Useful options

```powershell
# Test a different API host
.\.venv\Scripts\python.exe -m scripts.test_full_rag --base-url https://api.example.com --allow-external-llm

# Run selected labelled questions
.\.venv\Scripts\python.exe -m scripts.test_full_rag --question-ids 1 9 27 105 --allow-external-llm

# Keep the temporary tenant for manual UI inspection (normally it is deleted)
.\.venv\Scripts\python.exe -m scripts.test_full_rag --keep-data --allow-external-llm

# Increase the request timeout for a slow reasoning model
.\.venv\Scripts\python.exe -m scripts.test_full_rag --timeout 300 --allow-external-llm
```

The default cleanup removes only the exact clinic ID created by the run,
including its storage objects, Auth users, database rows, and clinic-specific
Chroma collection. Cleanup errors are shown in the final report.
