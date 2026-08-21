# Deployment runbook (free tier)

Architecture: Next.js frontend on **Vercel**, FastAPI backend on a **Hugging
Face Space** (Docker SDK), database/auth/storage on **Supabase**, vector
store on **Chroma Cloud** (so doctor-uploaded guidelines survive backend
restarts — see the root `Dockerfile` and `rag/config.py:get_chroma_client`),
LLM inference via **Groq**.

None of the steps below can be done on your behalf — they require your own
accounts/logins. This is the exact sequence.

## 1. Supabase

1. Create a project at supabase.com (or use an existing one).
2. In the SQL editor, run every file in `supabase/migrations/` **in order**
   (`0001` through `0006`).
3. From Project Settings -> API, copy: `Project URL`, `anon public` key,
   `service_role` key (service role is backend-only — never put it in
   `web/`).

## 2. Groq

Create a free key at https://console.groq.com/keys.

## 3. Chroma Cloud

Create a free account at https://www.trychroma.com (Chroma Cloud), then a
tenant + database. Copy the API key, tenant id, and database name — the
free tier is credit-based ($5 free credit, then metered), not a flat
forever-free cap, so check usage after the first week of real traffic.

## 4. Hugging Face Space (backend)

1. Create a new Space -> Docker SDK -> "Blank" template, any name (e.g.
   `tabeebak-backend`).
2. Either:
   - **Sync from GitHub** (Space Settings -> "Sync with a GitHub
     repository"), pointed at `ahmed522/clinical-rag`, so pushes to GitHub
     redeploy the Space automatically — the repo already has a root
     `Dockerfile` the Space will build; or
   - Push directly to the Space's own git remote:
     ```bash
     git remote add space https://huggingface.co/spaces/<you>/tabeebak-backend
     git push space feature/architecture:main
     ```
3. In Space Settings -> "Variables and secrets", add as **secrets**:
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
   - `LLM_PROVIDER=groq`, `LLM_API_KEY` (the Groq key from step 2)
   - `CHROMA_CLOUD_API_KEY`, `CHROMA_CLOUD_TENANT`, `CHROMA_CLOUD_DATABASE`
   - `CORS_ORIGINS` — leave as `http://localhost:3000` for now, come back
     and set it to the real Vercel URL after step 5
   - Optional, has working defaults: `LLM_MODEL`, `LLM_REASONING_EFFORT`,
     `LLM_TIMEOUT_SECONDS`, `EVIDENCE_VERIFIER_ENABLED`,
     `EVIDENCE_VERIFIER_TIMEOUT_SECONDS`, `MAX_UPLOAD_BYTES`
4. Wait for the build to finish, then note the Space's public URL, e.g.
   `https://<you>-tabeebak-backend.hf.space`.
5. Confirm `GET https://<you>-tabeebak-backend.hf.space/health` returns OK.

Note: HF Spaces' free CPU tier sleeps after inactivity — the first request
after a while will be slow (container cold start + model reload).

## 5. Vercel (frontend)

1. Import the GitHub repo into Vercel, set the project **root directory**
   to `web/` (Next.js auto-detected).
2. Add project env vars:
   - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (from
     step 1)
   - `NEXT_PUBLIC_API_BASE_URL` = the HF Space URL from step 4
3. Deploy, and note the resulting Vercel URL.

## 6. Close the loop

Go back to the HF Space secrets (step 4.3) and set `CORS_ORIGINS` to the
real Vercel URL (comma-separated if there's more than one, e.g. a preview
+ production URL), then restart the Space so it picks up the change.

## 7. Verify end-to-end

- `GET <space-url>/health` returns OK.
- Load the Vercel URL, log in, and as a doctor upload a real PDF — confirm
  ingestion succeeds. In the Chroma Cloud dashboard, confirm the clinic's
  collection now has vectors in it.
- Restart the HF Space (simulates a redeploy) and re-query the same
  document as a patient — this confirms vectors survived a restart, which
  is the entire reason for moving off local Chroma storage.
- Ask a patient-facing question and confirm an answer comes back with a
  citation (Groq responded successfully).
- If you have two clinics, confirm one clinic's guidelines never surface
  in another clinic's answers (tenant isolation) — mirrors
  `tests/test_tenant_isolation.py`, which covers this locally.
