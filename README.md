# Clinical RAG — Trusted Clinic Knowledge

A multi-tenant clinic SaaS and grounded RAG assistant over doctor-approved medical PDFs.
Doctors upload and verify sources; patients receive answers only from successfully
processed, verified documents belonging to their own clinic. Every displayed
clinical claim is mapped to an exact retrieved excerpt and passes a second
evidence-support and safety verification stage.

**Status: hackathon MVP.** The active path includes PDF quality validation, section-aware
chunking with page provenance, embeddings, Chroma retrieval, cross-encoder reranking,
grounded LLM generation, citation validation, abstention, FastAPI, Supabase/RLS, and a
Next.js UI. Retrieval and full-pipeline evaluation commands are included.

This is an information aid over clinic-provided sources. It does not diagnose patients
or replace a clinician.

---

## Sources

| File | Document | Pages |
|---|---|---|
| `data/source/source1.pdf` | NICE NG28 — *Type 2 diabetes in adults: management* | 131 |
| `data/source/source2.pdf` | WHO HEARTS-D — *Diagnosis and management of type 2 diabetes* | 35 |

Source metadata (title, publisher, URL, topic) is registered in `SOURCE_METADATA` at the
top of `rag/ingest.py`, **keyed by exact filename**. Adding a PDF without registering it
there still works, but its provenance fields will read `UNKNOWN` and the script warns.

The two guidelines are written for different contexts — NICE for the UK, WHO HEARTS-D for
primary care in lower-resource settings — so they can give different guidance on the same
question. Retrieval currently blends them with no precedence rule.

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on Unix
pip install -r requirements.txt

python -m rag.ingest             # PDFs        -> data/extracted/
python -m rag.preprocessing      # extracted   -> data/preprocessed/
python -m rag.chunk              # preprocessed-> data/chunks/chunks.json
python -m rag.embed              # chunks      -> data/chroma_db/
```

**Run the stages in that order.** Each reads the previous stage's output from disk; there
is no orchestrator. A full rebuild from the PDFs takes about 25 seconds.

Run everything as `python -m <package>.<module>` from the repo root — `rag/`, `app/`, and
`scripts/` are ordinary Python packages (each has an `__init__.py`), so no `sys.path`
tricks are needed to find `rag.config` or anything else.

For the multi-tenant MVP, copy `.env.example` to `.env`, apply all Supabase migrations in
order, then run the API and frontend:

```bash
uvicorn app.main:app --reload

cd web
cp .env.example .env.local
npm install
npm run dev
```

Migrations `0001` through `0006` must all be applied, in order, before the app will run
correctly — `0005_authz_fixes.sql` and `0006_remove_consult_mode.sql` are as required as
the earlier ones, not optional follow-ups.

Checks, runnable any time:

```bash
python -m scripts.evaluate_chunks      # chunk quality + page-citation verification
python -m scripts.evaluate_retrieval   # recall@k / MRR against the labelled query set
python -m scripts.evaluate_rag         # deterministic end-to-end RAG + citation report
python -m scripts.evaluate_rag --provider configured  # configured LLM; may incur cost
```

---

## Pipeline

```
data/source/*.pdf
   │
   ▼ rag/ingest.py        PyMuPDF text extraction, ligature + de-hyphenation repair,
   │                      source metadata attached
data/extracted/*.json     {source,title,publisher,url,topic,total_pages,
   │                       pages:[{page_number,text,char_count}]}
   │
   ▼ rag/preprocessing.py removes repeated page furniture (running titles, copyright
   │                      footers, page numbers) by FREQUENCY, not hardcoded regex;
   │                      labels copyright / table-of-contents pages
data/preprocessed/*.json  same shape + page_type per page
   │
   ▼ rag/chunk.py         detects section headings, splits into sections, then splits
   │                      long sections with overlap; maps every chunk back to the page
   │                      it starts on; skips non-content pages
data/chunks/chunks.json   [{chunk_id,text,section_title,page_number,source,
   │                        title,publisher,url,topic}]
   │
   ▼ rag/embed.py         all-MiniLM-L6-v2 (384-dim); wipes and rebuilds the index
data/chroma_db/           Chroma collection "clinical_rag_t2dm"
```

The app's own retrieval path (`app/services/retrieval.py`) reruns this same search
against a per-clinic collection at request time — there is no separate offline "query"
stage; `scripts/evaluate_retrieval.py` is what exercises retrieval quality standalone.

The offline `embed.py` command rebuilds only the configured single-tenant collection.
Application uploads use deterministic chunk IDs and document-level compensation, so a
failed clinic upload cannot intentionally wipe another clinic's collection.

---

## Configuration

All paths and tunable settings live in **`rag/config.py`** — chunk size, overlap, minimum
chunk length, furniture-detection thresholds, embedding model, collection name, `TOP_K`.
Change them there, not in the individual scripts. This is the pipeline's own config,
separate from `app/config.py` (Supabase, LLM provider, CORS, uploads) — the app imports
`rag.config` for the pipeline knobs it needs, never the other way around.

The generation LLM is swappable via `LLM_PROVIDER` in `.env` — `mock` (default, offline,
what the test suite runs on), `groq`, `anthropic`, `openai`, or `openrouter`. OpenRouter is
a free-tier alternative worth keeping as a manual failover for when Groq's rate limit is
hit mid-demo: switch `LLM_PROVIDER=openrouter`, restart, done. See `app/llm.py` and
`.env.example` for details and the current caveats on each provider.

Constants carry the measurement that justifies them. `MIN_CHUNK_CHARS = 60` is low on
purpose: `IF SYMPTOMATIC and FPG >=15 mmol/L ... gliclazide 80 mg 1 x daily` is 85
characters of real dosing guidance that a higher threshold would silently delete.

---

## Evaluation

### Chunk quality — `scripts/evaluate_chunks.py`

Size and word statistics, duplicates, required metadata, sentence boundaries, boilerplate
contamination, and **page-citation verification**: every chunk's text must actually appear
on the page it claims. That check exists because a fabricated citation is worse than no
citation in a clinical setting.

Current: 294 chunks, median 958 chars, **0% boilerplate**, 293/294 citations verified.

### Retrieval quality — `scripts/evaluate_retrieval.py`

Scored against `evaluation/clinical_queries.json`: **38 in-scope + 6 out-of-scope**
labelled queries. Every label was derived by reading the indexed documents directly — not
from prior knowledge of NICE/WHO guidance, and not from the retriever's own output.

That distinction matters. NG28's 2026 update changed first-line therapy to
**modified-release metformin plus an SGLT-2 inhibitor**; labels written from memory of an
earlier edition would be wrong, and labels taken from the retriever would bake in its bias.

Current reranked baseline (all-MiniLM-L6-v2, 30 candidates, `TOP_K=10`):

| k | recall@k | answer@k |
|---|---|---|
| 1 | 22/38 | 21/38 |
| 3 | 29/38 | 26/38 |
| 5 | **32/38** | 29/38 |
| 10 | **32/38** | 30/38 |

MRR 0.682 · out-of-scope rejection 6/6

`recall@k` = a chunk from the right source and page appeared. `answer@k` = it also
contained the expected text, which catches retrieving the right page but the wrong part.

### Full-pipeline quality — `scripts/evaluate_rag.py`

The deterministic mock baseline runs retrieval, reranking, structured claim generation,
exact-excerpt validation, claim verification, citation resolution, and latency reporting
over the same 44 questions:

- Grounded in-scope responses: 38/38
- Valid and exact citations: 38/38
- Correct-page citations: 22/38
- Citations containing labelled answer evidence: 21/38
- Mechanically covered claims: 42/42
- Verifier-supported claims: 42/42
- Correct out-of-scope abstentions: 2/6
- Total latency: p50 756 ms, p95 896 ms on the review machine

The mock intentionally quotes and cites the first retrieved source, so these results expose
top-1 citation quality and show why a real generation provider must be evaluated separately.
Run `--provider configured` before the demo to measure the configured model's sufficiency
judgement and abstention behavior. That run may incur provider cost.

---

## Known limitations

- **6 of 38 queries miss entirely** — the answer is not in the top 10. Four are WHO pages
  (metformin contraindications, blood pressure/lipids, DKA/HHS, urgent referral).
- **No usable abstention threshold.** In-scope and out-of-scope similarity scores overlap:
  worst in-scope 0.833, worst out-of-scope 0.755. Any single cut-off either admits
  unanswerable questions or refuses real ones. `WEAK_MATCH_DISTANCE` in `rag/config.py`
  records this but must not be relied on as a safety mechanism.
- **Tables and figures are lost as structure.** Extraction linearises them, so dose
  escalation tables and treatment algorithms become ambiguous token streams, and figure
  content that lives in an image is unavailable — only its caption is indexed.
- **~56% of chunks start mid-sentence, ~68% end mid-sentence.** A cut can strand a negation
  or qualifier ("do not offer", "only if"), which inverts clinical meaning.
- **One known bad citation** — the WHO cover-page chunk; page 2 is dropped as empty, making
  pages 1 and 3 adjacent in the concatenated text.
- **No document versioning.** `SOURCE_METADATA` has no publication or retrieval date, so
  nothing detects a superseded guideline.
- **Scanned/image-only PDFs are rejected, not OCR'd.** The ingestion quality gate detects
  an unreadable scan and rejects it instead of creating an empty index; upload a
  searchable PDF.

---

## Not implemented

Source precedence between conflicting guidelines · durable background ingestion ·
human clinical adjudication of evaluation labels · Docker · CI.

---

## Suggested next steps

1. **Run both evaluators** before and after every RAG change; keep the JSON reports.
2. **Investigate the 6 candidate misses.** A reranker cannot reorder evidence that dense
   retrieval never returned.
3. **Add a small diverse PDF suite** covering scans, columns, tables, and mixed layouts.
4. **Try clinical or multilingual embeddings only in shadow**, and replace the current
   model only when retrieval and full-pipeline metrics improve.

---

## Layout

```
data/source/           input PDFs (tracked)
data/extracted/        rag/ingest.py output (tracked — small, reviewable)
data/preprocessed/     rag/preprocessing.py output (tracked)
data/chunks/           rag/chunk.py output (tracked)
data/chroma_db/        vector index (gitignored) — holds BOTH the single-tenant
                        CLI collection AND every live clinic's collection from
                        the running app; never delete this directory casually
evaluation/            labelled query set + evaluation reports
docs/sources.md        source provenance notes
rag/                   pipeline library — config, ingest, preprocessing, chunk,
                        embed, rerank. Imports nothing from app/.
app/                   FastAPI web app. Imports rag/, never the reverse.
scripts/               entrypoints that use both layers: the evaluators and
                        demo.py. Nothing imports scripts/ — these are only run
                        directly (`python -m scripts.<name>`).
```

Licensed under the terms in `LICENSE`. The guideline PDFs remain the copyright of NICE and
the WHO respectively.
