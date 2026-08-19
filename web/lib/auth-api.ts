import type { Session } from "@supabase/supabase-js";

import { API_BASE_URL, supabase } from "./supabase";
import { withTimeout } from "./timeout";

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  role: "clinic_admin" | "doctor" | "patient";
  clinic_id: string;
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
  const target = role === "doctor" ? "/doctor" : role === "patient" ? "/patient" : "/clinic";
  // A full navigation makes the AuthProvider start from the newly persisted
  // Supabase session. It avoids a race between router.replace and the auth
  // state event immediately after registration/login.
  window.location.assign(target);
}
