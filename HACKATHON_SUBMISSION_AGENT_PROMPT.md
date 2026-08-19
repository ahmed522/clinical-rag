# Clinical RAG Hackathon Submission — Agent Handoff Prompt

Copy this complete prompt into the implementation agent. It is intentionally strict: the project handles medical information, multi-tenant data, authentication, and externally hosted services. Never report a check as passed unless it was actually executed.

---

## Prompt

You are the senior AI architect, RAG evaluation engineer, full-stack release engineer, and security reviewer responsible for making this repository submission-ready for a hackathon.

Repository root:

```text
C:\Users\pc\OneDrive\Desktop\clinical-rag
```

The product is a multi-tenant clinic SaaS. Clinic admins manage the clinic and doctors; doctors register patients and upload/verify trusted medical PDFs; patients use a RAG chatbot that must answer only from their clinic's verified documents. The hackathon is primarily judged on the RAG pipeline, grounding, citations, safety, and evaluation—not on adding unrelated product features.

Your mission is to audit, configure, fix, test, and document the complete submission. Work from evidence in the repository and live services. Do not guess, weaken safety gates, fabricate evaluation results, reset the database, expose secrets, or change embedding/chunking/reranking settings without a before/after evaluation proving improvement.

### Non-negotiable behavior

- Preserve FastAPI, Next.js, Supabase Auth/Postgres/Storage with RLS, Chroma, the provider abstraction, and existing tenant/business workflows.
- Medical answers must remain fail-closed. If retrieval, structured generation, exact-excerpt validation, semantic verification, or safety checks fail, display `Insufficient Evidence` or the appropriate fixed refusal.
- Do not disable `EVIDENCE_VERIFIER_ENABLED` to make the demo appear successful.
- Never place `SUPABASE_SERVICE_ROLE_KEY` or `LLM_API_KEY` in `web/.env.local`, browser code, logs, screenshots, commits, reports, or chat output.
- Do not run `supabase db reset`, delete existing clinics/users/documents, or modify live migration history destructively.
- Do not run live tests that create remote users/tenants until the target Supabase project is confirmed. Use unique test emails and verify cleanup behavior.
- Treat authentication, English/Arabic switching, clinic isolation, citations, and safety refusals as release blockers.
- Preserve legacy message rendering and existing data.

## 1. Establish the real current state

Before editing:

1. Read `README.md`, `.env.example`, `web/.env.example`, both config modules, all migrations, current evaluation reports, and applicable `AGENTS.md` instructions.
2. Inspect `git status` and preserve unrelated user changes. The working tree is currently large and uncommitted.
3. Record installed Python, Node, npm, Supabase CLI, Tesseract, and model-cache availability.
4. Confirm the actual backend and frontend processes/ports. Do not assume an HTTP `200` means browser hydration or authentication works.
5. Compare documented configuration against runtime configuration and fix drift.

Known drift that must be resolved:

- Runtime uses `LLM_TIMEOUT_SECONDS=45`; `.env.example` currently says `25`.
- Runtime supports `LLM_REASONING_EFFORT` with default `medium`; `.env.example` currently omits it.
- `README.md` discusses migrations only through `0004`; migrations `0005_authz_fixes.sql` and `0006_remove_consult_mode.sql` now exist.
- `scripts/demo.py` still uses the obsolete workflow where a clinic admin uploads documents and registers patients. The current workflow requires an admin to register a doctor, then the doctor uploads/verifies documents and registers patients.
- The API root comment still says no frontend exists.
- Python dependencies are split between `requirements.txt` and an incomplete `pyproject.toml`; make the documented installation path reproducible.
- The user currently reports that English switching and sign-in do not work in the rendered browser. Treat this as an unresolved blocker even if lint/build/route HTTP checks pass.

## 2. Required environment configuration

Create local environment files only if absent. Never commit their values.

Backend `.env` must contain valid values for:

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<public-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<backend-only-service-role-key>

CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

LLM_PROVIDER=groq
LLM_API_KEY=<provider-key>
LLM_MODEL=openai/gpt-oss-120b
LLM_REASONING_EFFORT=medium
LLM_TIMEOUT_SECONDS=45
EVIDENCE_VERIFIER_ENABLED=true
EVIDENCE_VERIFIER_TIMEOUT_SECONDS=15

MAX_UPLOAD_BYTES=52428800
PDF_OCR_ENABLED=true
PDF_OCR_LANGUAGE=eng
PDF_OCR_DPI=200
```

If a different configured provider/model is intentionally used, document it and run the same evaluation with that exact provider/model. `mock` is for deterministic tests, not the final judged demo.

Frontend `web/.env.local` must contain only public configuration:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://<same-project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<same-public-anon-key>
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Validate that:

- Backend and frontend point to the same Supabase project.
- `SUPABASE_URL` is the bare project URL, not `/rest/v1` or `/auth/v1`.
- No secret appears in tracked files or frontend bundles.
- CORS contains the exact origin used for the demo.
- Node is version 20 or newer.
- Provider, Supabase, Hugging Face/model downloads, and Tesseract are available on the demo network/machine.
- Embedding and reranker models are downloaded/pre-warmed before the presentation.

## 3. Supabase and authorization configuration

Verify and apply all migrations in this exact order to the confirmed project:

```text
0001_schema_and_rls.sql
0002_roles_and_scheduling.sql
0003_rag_mvp_reliability.sql
0004_structured_rag_evidence.sql
0005_authz_fixes.sql
0006_remove_consult_mode.sql
```

Prefer the Supabase CLI and tracked migration history. If this project was originally configured through the Dashboard SQL Editor, first inspect migration history and avoid creating a false `db push` state. Never reset the hosted database.

Verify after migration:

- Required message evidence/audit columns exist.
- Chat mode constraint permits only `general` and `triage`.
- Existing `consult` sessions were relabelled to `general` without message deletion.
- The `guidelines` storage bucket and its policies exist.
- RLS is enabled on every tenant table.
- Admin, doctor, and patient permissions match the current three-role workflow.
- Patients cannot change their own `clinic_id`, `doctor_id`, or `auth_id`.
- Patients cannot access unverified/not-ready documents or storage objects.
- Cross-clinic reads/writes fail.
- Old clinics have a non-null unique slug.
- `messages_evidence_strength_check` accepts only `high`, `medium`, `low`, `insufficient`, or null.

## 4. RAG and ingestion configuration

Keep the measured baseline unless an unchanged labelled dataset proves a better alternative:

```text
Embedding model: sentence-transformers/all-MiniLM-L6-v2
Chunk size: 1000 characters
Chunk overlap: 150 characters
Minimum chunk length: 60 characters
Initial retrieval TOP_K: 10
Generation context RETRIEVAL_K: 5
Reranking enabled: true
Reranker: cross-encoder/ms-marco-MiniLM-L-6-v2
Reranker candidate pool: 30
Loose off-domain distance gate: 1.65
Prompt version: 2026-08-18.4 or the newer version actually present at submission
```

Validate the complete medical pipeline:

```text
trusted PDF upload
→ extraction/OCR quality gate
→ preprocessing
→ section/page-aware chunking
→ deterministic chunk IDs
→ clinic-isolated Chroma collection
→ retrieve candidate pool
→ rerank
→ final five context chunks
→ structured claim generation
→ source-ID and exact-excerpt validation
→ semantic evidence/safety verifier
→ evidence strength
→ audit persistence
→ structured UI rendering
```

Test at least these PDFs:

- Searchable text PDF.
- Scanned/image PDF requiring OCR.
- Multi-column or table-heavy PDF.
- Invalid/non-PDF upload.
- Empty/unreadable PDF.
- Duplicate upload.
- A source with and without a public URL.

Each accepted document must expose title, publisher, topic, source URL when present, page count, chunk count, extraction/OCR warnings, status, verification identity/date, and provenance. Only `ready + verified` documents may contribute to patient answers.

## 5. Authentication and frontend blockers

Repair and interactively test the rendered browser—not only HTTP responses—the following flows:

1. Every public/auth page visibly offers `English` and `العربية`.
2. Selecting English immediately changes labels and document direction to LTR and persists after refresh/navigation.
3. Selecting Arabic changes direction to RTL while generated medical answer text keeps its independent direction.
4. Clinic registration creates one tenant and confirmed clinic-admin account, persists the returned access/refresh session, and navigates to `/clinic`.
5. Logging out and signing in again with that admin account succeeds and returns to `/clinic`.
6. Admin registers a doctor; doctor signs in, changes the initial password, and reaches `/doctor`.
7. Doctor registers a patient; patient changes the initial password, completes onboarding, and reaches `/patient`.
8. Wrong-role navigation redirects safely without infinite loading or redirect loops.
9. Invalid credentials, Supabase outage, API outage, and timeouts show actionable errors rather than indefinite `جارٍ التحميل…`.
10. Session restoration and token refresh do not clear chat history or create duplicate sessions.

Centralize frontend API/auth calls where practical and add browser tests for these flows. A successful Next.js build is necessary but not sufficient.

## 6. Evaluation configuration and acceptance gates

Use the unchanged labelled dataset in `evaluation/clinical_queries.json` for every before/after comparison. Preserve JSON reports with provider, model, prompt version, dataset version/size, configuration, metrics, failures, and stage latency.

Run:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
.\.venv\Scripts\python.exe -m pytest tests -q --ignore=tests/test_end_to_end.py

.\.venv\Scripts\python.exe src\evaluate_chunks.py
.\.venv\Scripts\python.exe src\evaluate_retrieval.py
.\.venv\Scripts\python.exe src\evaluate_rag.py
.\.venv\Scripts\python.exe src\evaluate_rag.py --provider configured --output evaluation\rag_report_configured.json

cd web
npm run lint
npm run build
```

Only enable offline Hugging Face mode after confirming the embedding and reranker models are already cached. Otherwise allow the initial model download and then repeat offline.

Run the configured-provider evaluation only when the API key is present and use the labelled evaluation data—not real patient records. Record provider cost/rate-limit failures honestly.

Then run the live integration/E2E suite against the confirmed test project. It creates remote auth/tenant data, so use unique test identities and verify cleanup. Do not point destructive cleanup at a production project.

Required acceptance gates:

- 100% valid source/chunk references for displayed grounded answers.
- 100% exact supporting-excerpt validation.
- 100% citation coverage across displayed clinical claims.
- No displayed claim rejected by the semantic verifier.
- Every explicit patient-specific diagnosis/dosage case refuses safely.
- Out-of-scope questions abstain.
- Existing retrieval baseline does not regress.
- Latency and failure reasons appear in reports.
- Cross-clinic isolation tests pass.
- Python tests pass.
- Frontend lint and production build pass.
- Browser tests pass at desktop and mobile widths in English and Arabic.

Do not hide weak metrics. Explain them and demonstrate the safety/refusal behavior.

## 7. Demo and operational readiness

Update `scripts/demo.py` to the current workflow:

```text
register clinic admin
→ admin registers doctor
→ doctor changes password
→ doctor uploads PDF
→ doctor reviews processing/OCR and verifies PDF
→ doctor registers patient
→ patient changes password and completes onboarding
→ patient asks supported question
→ UI displays recommendation, evidence, citations, evidence strength, safety, and audit drawer
→ patient asks unsupported and patient-specific questions
→ system refuses helpfully
→ admin opens RAG quality dashboard
```

The demo must also show tenant isolation using two clinics or an automated isolation test result. Keep the presentation path under approximately seven minutes and pre-warm models before judges arrive.

Confirm startup from a clean terminal:

```powershell
cd C:\Users\pc\OneDrive\Desktop\clinical-rag
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd C:\Users\pc\OneDrive\Desktop\clinical-rag\web
npm run dev
```

Verify:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:3000/login`
- Backend schema includes `/evaluation/latest` and refresh tokens.
- No stale process is serving an older frontend/backend build.
- Port 8000/3000 conflicts are resolved.
- Dependency failures are visible and do not produce unsafe medical answers.

## 8. Documentation, packaging, and submission hygiene

Before final handoff:

- Reconcile `requirements.txt`, `pyproject.toml`, and `uv.lock` so a fresh installation contains FastAPI, Supabase, provider, RAG, and test dependencies.
- Update `.env.example` with every supported variable and safe defaults, including reasoning effort and the actual timeout.
- Update README setup, migrations `0001–0006`, current role workflow, current evaluation results, startup commands, OCR prerequisites, and known limitations.
- Remove stale claims such as “there is no frontend,” “appointments are not built,” or admin-owned document/patient workflows.
- Confirm `.env`, `.env.local`, Chroma binaries, uploaded clinic PDFs, logs, caches, temporary files, and service keys are not tracked.
- Keep the labelled evaluation set and deliberate before/after reports; clearly label mock versus configured-provider results.
- Review source PDF licensing/provenance and do not imply ownership of NICE/WHO content.
- Split and commit changes into understandable units if repository submission includes Git history.
- Do not include unrelated machine-specific files.

## 9. Final deliverables

Create `HACKATHON_READINESS_REPORT.md` containing:

1. Exact environment/configuration used, with secrets redacted.
2. Applied migration list and verification results.
3. Provider/model/prompt/embedding/reranker/chunking configuration.
4. Python, frontend, browser, integration, and tenant-isolation test results.
5. Mock and configured-provider evaluation tables.
6. Latency, failed cases, and known limitations.
7. Manual desktop/mobile English/Arabic QA matrix.
8. Five-to-seven-minute demo sequence.
9. Remaining blockers labelled `critical`, `high`, `medium`, or `low`.
10. Final `READY` or `NOT READY` decision with evidence.

If any critical acceptance gate fails, return `NOT READY`; fix it if safely possible and rerun the affected validation. Never replace a missing test result with an assumption.

---

## Submission priority

Work in this order:

1. Secrets, environment consistency, and correct Supabase target.
2. Apply/verify migrations and tenant authorization.
3. Fix rendered-browser English, registration, login, and role redirects.
4. Validate doctor PDF upload/verification and patient onboarding.
5. Validate structured RAG answers, exact citations, verifier, and refusals.
6. Run retrieval plus full configured-provider evaluation.
7. Run integration/browser/mobile tests.
8. Update demo, documentation, packaging, and final readiness report.

Do not spend time on cosmetic redesign or new business features while any item above remains failing.
