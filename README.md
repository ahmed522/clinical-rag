# Clinical RAG — Type 2 Diabetes

A retrieval system over trusted clinical guidelines for type 2 diabetes. It ingests
guideline PDFs, splits them into section-aware chunks that keep their source and page
number, embeds them, and retrieves the passages relevant to a clinical question.

**Status: retrieval prototype.** The pipeline runs end to end from PDF to ranked
passages, and retrieval quality is measured against a labelled evaluation set. There is
**no answer generation yet** — no LLM stage, no citation rendering, no abstention. See
[Not implemented](#not-implemented) before assuming otherwise.

This is an information-retrieval aid over two specific documents. It is not a clinical
decision tool and does not give medical advice.

---

## Sources

| File | Document | Pages |
|---|---|---|
| `data/source/source1.pdf` | NICE NG28 — *Type 2 diabetes in adults: management* | 131 |
| `data/source/source2.pdf` | WHO HEARTS-D — *Diagnosis and management of type 2 diabetes* | 35 |

Source metadata (title, publisher, URL, topic) is registered in `SOURCE_METADATA` at the
top of `src/ingest.py`, **keyed by exact filename**. Adding a PDF without registering it
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

python src/ingest.py            # PDFs        -> data/extracted/
python src/preprocessing.py     # extracted   -> data/preprocessed/
python src/chunk.py             # preprocessed-> data/chunks/chunks.json
python src/embed.py             # chunks      -> data/chroma_db/
python src/query.py             # ask the 10 built-in test questions
```

**Run the stages in that order.** Each reads the previous stage's output from disk; there
is no orchestrator. A full rebuild from the PDFs takes about 25 seconds.

Run the scripts as `python src/<name>.py` (not `python -m src.<name>`) — that puts `src/`
on the import path so they can find `config.py`.

Checks, runnable any time:

```bash
python src/evaluate_chunks.py      # chunk quality + page-citation verification
python src/evaluate_retrieval.py   # recall@k / MRR against the labelled query set
```

---

## Pipeline

```
data/source/*.pdf
   │
   ▼ ingest.py            PyMuPDF text extraction, ligature + de-hyphenation repair,
   │                      source metadata attached
data/extracted/*.json     {source,title,publisher,url,topic,total_pages,
   │                       pages:[{page_number,text,char_count}]}
   │
   ▼ preprocessing.py     removes repeated page furniture (running titles, copyright
   │                      footers, page numbers) by FREQUENCY, not hardcoded regex;
   │                      labels copyright / table-of-contents pages
data/preprocessed/*.json  same shape + page_type per page
   │
   ▼ chunk.py             detects section headings, splits into sections, then splits
   │                      long sections with overlap; maps every chunk back to the page
   │                      it starts on; skips non-content pages
data/chunks/chunks.json   [{chunk_id,text,section_title,page_number,source,
   │                        title,publisher,url,topic}]
   │
   ▼ embed.py             all-MiniLM-L6-v2 (384-dim); wipes and rebuilds the index
data/chroma_db/           Chroma collection "clinical_rag_t2dm"
   │
   ▼ query.py             similarity search, top 10, results + provenance
data/query_results.json
```

`embed.py` **deletes `data/chroma_db/` and rebuilds it** on every run. That is deliberate —
without it, re-running appends duplicate vectors — but it means a hand-curated index would
be lost.

---

## Configuration

All paths and tunable settings live in **`src/config.py`** — chunk size, overlap, minimum
chunk length, furniture-detection thresholds, embedding model, collection name, `TOP_K`.
Change them there, not in the individual scripts.

Constants carry the measurement that justifies them. `MIN_CHUNK_CHARS = 60` is low on
purpose: `IF SYMPTOMATIC and FPG >=15 mmol/L ... gliclazide 80 mg 1 x daily` is 85
characters of real dosing guidance that a higher threshold would silently delete.

---

## Evaluation

### Chunk quality — `src/evaluate_chunks.py`

Size and word statistics, duplicates, required metadata, sentence boundaries, boilerplate
contamination, and **page-citation verification**: every chunk's text must actually appear
on the page it claims. That check exists because a fabricated citation is worse than no
citation in a clinical setting.

Current: 294 chunks, median 958 chars, **0% boilerplate**, 293/294 citations verified.

### Retrieval quality — `src/evaluate_retrieval.py`

Scored against `evaluation/clinical_queries.json`: **38 in-scope + 6 out-of-scope**
labelled queries. Every label was derived by reading the indexed documents directly — not
from prior knowledge of NICE/WHO guidance, and not from the retriever's own output.

That distinction matters. NG28's 2026 update changed first-line therapy to
**modified-release metformin plus an SGLT-2 inhibitor**; labels written from memory of an
earlier edition would be wrong, and labels taken from the retriever would bake in its bias.

Current baseline (all-MiniLM-L6-v2, `TOP_K=10`):

| k | recall@k | answer@k |
|---|---|---|
| 1 | 18/38 | 17/38 |
| 3 | 22/38 | 20/38 |
| 5 | 27/38 | 25/38 |
| 10 | **32/38** | 29/38 |

MRR 0.574 · out-of-scope rejection 6/6

`recall@k` = a chunk from the right source and page appeared. `answer@k` = it also
contained the expected text, which catches retrieving the right page but the wrong part.

---

## Known limitations

- **6 of 38 queries miss entirely** — the answer is not in the top 10. Four are WHO pages
  (metformin contraindications, blood pressure/lipids, DKA/HHS, urgent referral).
- **No usable abstention threshold.** In-scope and out-of-scope similarity scores overlap:
  worst in-scope 0.833, worst out-of-scope 0.755. Any single cut-off either admits
  unanswerable questions or refuses real ones. `WEAK_MATCH_DISTANCE` in `config.py` records
  this but must not be relied on as a safety mechanism.
- **Tables and figures are lost as structure.** Extraction linearises them, so dose
  escalation tables and treatment algorithms become ambiguous token streams, and figure
  content that lives in an image is unavailable — only its caption is indexed.
- **~56% of chunks start mid-sentence, ~68% end mid-sentence.** A cut can strand a negation
  or qualifier ("do not offer", "only if"), which inverts clinical meaning.
- **`chunk_id` is a fresh UUID on every run**, so incremental indexing is impossible and
  chunk files cannot be diffed directly.
- **One known bad citation** — the WHO cover-page chunk; page 2 is dropped as empty, making
  pages 1 and 3 adjacent in the concatenated text.
- **No document versioning.** `SOURCE_METADATA` has no publication or retrieval date, so
  nothing detects a superseded guideline.
- **No automated tests.** pytest is installed; no suite written yet.

---

## Not implemented

Reranking · LLM answer generation · grounded citation rendering · abstention on
insufficient evidence · source prioritisation between NICE and WHO · API or UI ·
Docker · CI.

---

## Suggested next steps

1. **Add a reranker.** 32/38 answers already reach the top 10 but are poorly ordered
   (MRR 0.574) — exactly the gap a cross-encoder closes. `evaluate_retrieval.py` measures
   whether it worked.
2. **Investigate the 6 misses**, concentrated in WHO content. No reranker can reorder a
   candidate that was never retrieved.
3. **Try a clinical-domain embedding model** and re-measure.
4. **Only then add generation** — with mandatory inline citations, an explicit
   "not covered by these guidelines" path, and post-generation validation that every cited
   page was actually retrieved. Answering confidently with no ability to abstain is the
   riskiest possible configuration for a clinical system.

---

## Layout

```
data/source/           input PDFs (tracked)
data/extracted/        ingest.py output (tracked — small, reviewable)
data/preprocessed/     preprocessing.py output (tracked)
data/chunks/           chunk.py output (tracked)
data/chroma_db/        vector index (gitignored — rebuilt every run)
data/query_results.json  query.py output (gitignored)
evaluation/            labelled query set + retrieval report
docs/sources.md        source provenance notes
src/                   pipeline scripts + config.py
```

Licensed under the terms in `LICENSE`. The guideline PDFs remain the copyright of NICE and
the WHO respectively.
