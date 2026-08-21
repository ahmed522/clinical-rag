# Deployment runbook (free tier)

Architecture: Next.js frontend on **Vercel**, FastAPI backend on a **Render**
free web service, database/auth/storage on **Supabase**, vector store on
**Chroma Cloud** (so doctor-uploaded guidelines survive backend restarts —
see `rag/config.py:get_chroma_client`), LLM inference via **Groq**.

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

## 4. Render (backend)

Render's Docker SDK isn't needed here — the repo's `render.yaml` blueprint
tells Render to run the backend as a plain Python service (no container
build), which is what the free tier supports without a credit card.

1. Go to render.com, sign up / log in (no card required for the free
   tier), and click **New -> Blueprint**.
2. Connect the `ahmed522/clinical-rag` GitHub repo. Render will detect
   `render.yaml` at the repo root and propose a `tabeebak-backend` web
   service — confirm it.
3. Before the first deploy finishes, go to the service's **Environment**
   tab and add these as secrets (`render.yaml` intentionally doesn't carry
   any of these — they're set by hand):
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
   - `LLM_PROVIDER=groq`, `LLM_API_KEY` (the Groq key from step 2)
   - `CHROMA_CLOUD_API_KEY`, `CHROMA_CLOUD_TENANT`, `CHROMA_CLOUD_DATABASE`
   - `CORS_ORIGINS` — leave as `http://localhost:3000` for now, come back
     and set it to the real Vercel URL after step 5
   - Optional, has working defaults: `LLM_MODEL`, `LLM_REASONING_EFFORT`,
     `LLM_TIMEOUT_SECONDS`, `EVIDENCE_VERIFIER_ENABLED`,
     `EVIDENCE_VERIFIER_TIMEOUT_SECONDS`, `MAX_UPLOAD_BYTES`
4. Wait for the build/deploy to finish, then note the service's public
   URL, e.g. `https://tabeebak-backend.onrender.com`.
5. Confirm `GET https://tabeebak-backend.onrender.com/health` returns OK.

Two things to expect on Render's free tier:
- It **sleeps after ~15 minutes of inactivity** — the first request after
  idling will be slow (cold start).
- The filesystem is **not persisted across deploys**, so
  `render.yaml` sets `HF_LOCAL_FILES_ONLY=false`, meaning the embedding
  and reranker models download fresh on first use after every deploy
  (and every wake from sleep, if the instance was fully recycled) — a
  slower first request, not a failure.

## 5. Vercel (frontend)

1. Import the GitHub repo into Vercel, set the project **root directory**
   to `web/` (Next.js auto-detected).
2. Add project env vars:
   - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (from
     step 1)
   - `NEXT_PUBLIC_API_BASE_URL` = the Render URL from step 4
3. Deploy, and note the resulting Vercel URL.

## 6. Close the loop

Go back to the Render service's Environment tab (step 4.3) and set
`CORS_ORIGINS` to the real Vercel URL (comma-separated if there's more
than one, e.g. a preview + production URL) — this triggers a redeploy
automatically.

## 7. Verify end-to-end

- `GET <render-url>/health` returns OK.
- Load the Vercel URL, log in, and as a doctor upload a real PDF — confirm
  ingestion succeeds. In the Chroma Cloud dashboard, confirm the clinic's
  collection now has vectors in it.
- Manually restart the Render service (Manual Deploy -> Deploy latest
  commit, or just wait for it to sleep and wake) and re-query the same
  document as a patient — this confirms vectors survived a restart, which
  is the entire reason for moving off local Chroma storage.
- Ask a patient-facing question and confirm an answer comes back with a
  citation (Groq responded successfully).
- If you have two clinics, confirm one clinic's guidelines never surface
  in another clinic's answers (tenant isolation) — mirrors
  `tests/test_tenant_isolation.py`, which covers this locally.
