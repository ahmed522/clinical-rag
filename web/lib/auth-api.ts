import type { Session } from "@supabase/supabase-js";

import { API_BASE_URL, supabase } from "./supabase";
import { withTimeout } from "./timeout";

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  role: "clinic_admin" | "doctor" | "patient" | "it";
  clinic_id: string;
}

export class AuthSessionUnavailableError extends Error {
  constructor() {
    super("The authentication session is missing or expired");
    this.name = "AuthSessionUnavailableError";
  }
}

function withBearer(init: RequestInit | undefined, accessToken: string): RequestInit {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  return { ...init, headers };
}

/**
 * Call an authenticated FastAPI endpoint with the freshest Supabase token.
 * A token can expire while a dashboard tab remains open; retry exactly once
 * after an explicit refresh so a stale token does not silently disable UI.
 */
export async function authenticatedFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  requestTimeoutMs = 20_000,
): Promise<Response> {
  const { data: current, error: sessionError } = await withTimeout(
    supabase.auth.getSession(),
    20_000,
  );
  if (sessionError || !current.session) throw new AuthSessionUnavailableError();

  let response = await withTimeout(
    fetch(input, withBearer(init, current.session.access_token)),
    requestTimeoutMs,
  );
  if (response.status !== 401) return response;

  const { data: refreshed, error: refreshError } = await withTimeout(
    supabase.auth.refreshSession(),
    20_000,
  );
  if (refreshError || !refreshed.session) throw new AuthSessionUnavailableError();

  response = await withTimeout(
    fetch(input, withBearer(init, refreshed.session.access_token)),
    requestTimeoutMs,
  );
  if (response.status === 401) throw new AuthSessionUnavailableError();
  return response;
}

async function readError(response: Response): Promise<string> {
  const body = await response.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : "Authentication failed";
}

export async function loginWithApi(email: string, password: string): Promise<Session> {
  const response = await withTimeout(
    fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
    20_000,
  );

  if (!response.ok) throw new Error(await readError(response));
  return establishSession((await response.json()) as AuthTokenResponse);
}

export async function establishSession(tokens: AuthTokenResponse): Promise<Session> {
  if (!tokens.access_token || !tokens.refresh_token) {
    throw new Error("The server returned an incomplete session");
  }

  const { data, error } = await withTimeout(
    supabase.auth.setSession({
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
    }),
    20_000,
  );

  if (error || !data.session) throw error ?? new Error("Could not establish the session");
  return data.session;
}

export function navigateToRole(role: string | undefined): void {
  const target =
    role === "doctor" ? "/doctor" : role === "patient" ? "/patient" : role === "it" ? "/it" : "/clinic";
  // A full navigation makes the AuthProvider start from the newly persisted
  // Supabase session. It avoids a race between router.replace and the auth
  // state event immediately after registration/login.
  window.location.assign(target);
}
