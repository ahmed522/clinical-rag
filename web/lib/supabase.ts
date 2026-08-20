import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

const SUPABASE_REQUEST_TIMEOUT_MS = 12_000;

if (!url || !anonKey) {
  // Fails loudly at import time rather than on the first click — a
  // missing env var otherwise surfaces as an opaque network error deep
  // inside whichever component happened to touch Supabase first.
  throw new Error(
    "NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY are not set (check web/.env.local)"
  );
}

// One client for the whole app. It holds no privilege of its own beyond
// the anon key — every read/write a signed-in user makes through it is
// subject to the Postgres RLS policies in supabase/migrations/, exactly
// as it is for the FastAPI service's forwarded-JWT client.
const timedFetch: typeof fetch = async (input, init) => {
  const controller = new AbortController();
  const upstreamSignal = init?.signal;
  const forwardAbort = () => controller.abort();

  if (upstreamSignal?.aborted) controller.abort();
  else upstreamSignal?.addEventListener("abort", forwardAbort, { once: true });

  const timer = window.setTimeout(() => controller.abort(), SUPABASE_REQUEST_TIMEOUT_MS);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
    upstreamSignal?.removeEventListener("abort", forwardAbort);
  }
};

export const supabase = createClient(url, anonKey, {
  global: { fetch: timedFetch },
});

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL!;
