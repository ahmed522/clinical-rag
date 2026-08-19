"use client";

import type { Session } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useState } from "react";

import { supabase } from "./supabase";
import { withTimeout } from "./timeout";

const AUTH_INITIALIZATION_TIMEOUT_MS = 8_000;

export type Role = "clinic_admin" | "doctor" | "patient" | null;

export interface Profile {
  id: string;
  must_change_password: boolean;
  onboarding_completed?: boolean; // doctors don't have this column; only patients
  [key: string]: unknown;
}

interface AuthContextValue {
  session: Session | null;
  role: Role;
  clinicId: string | null;
  profile: Profile | null;
  profileLoading: boolean;
  loading: boolean;
  refreshProfile: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const TABLE_FOR_ROLE: Record<string, string> = {
  doctor: "doctors",
  patient: "patients",
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState(false);
  // Tracks which identity `profile` was actually loaded for, so a profile
  // fetched for a previous (or no) user can never be read as "current" —
  // closes the gap where must_change_password briefly reads as false for
  // a new session before its own profile fetch resolves.
  const [profileForUserId, setProfileForUserId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    void withTimeout(
      supabase.auth.getSession(),
      AUTH_INITIALIZATION_TIMEOUT_MS,
      "Authentication service is unavailable",
    )
      .then(({ data }) => {
        if (active) setSession(data.session);
      })
      .catch(() => {
        // A dependency outage must never leave every route on an infinite
        // loading screen. Signed-out pages remain usable and sign-in shows
        // the actionable connection error.
        if (active) setSession(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    // Keeps this in sync across tabs and after token refresh, not just on
    // the initial load — a session that goes stale mid-visit would
    // otherwise silently start failing RLS-protected requests.
    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      if (!active) return;
      setSession(newSession);
      setLoading(false);
    });

    return () => {
      active = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  // clinic_id and role live in app_metadata, set only by the service role
  // during registration (app/routers/auth.py) — never user_metadata, which
  // the signed-in user could edit themselves. Reading them from anywhere
  // else would be reading a value the caller could have forged.
  const metadata = session?.user?.app_metadata ?? {};
  const role = (metadata.role as Role) ?? null;
  const clinicId = (metadata.clinic_id as string) ?? null;
  const userId = session?.user?.id ?? null;

  // must_change_password / onboarding_completed live in the doctors/
  // patients row itself, not the JWT — a value the row's own RLS
  // self-update policy lets the user clear, unlike app_metadata.
  //
  // A network error here must NOT read as "no profile, gate satisfied" —
  // RequireRole's must_change_password check is the only thing standing
  // between a first-login account and the full dashboard, so a failed
  // fetch has to keep the gate closed (stay not-ready) rather than open it.
  const loadProfile = async () => {
    if (!userId || !role || !TABLE_FOR_ROLE[role]) {
      setProfile(null);
      setProfileError(false);
      setProfileForUserId(userId);
      setProfileLoading(false);
      return;
    }
    setProfileLoading(true);
    setProfileError(false);
    try {
      const { data } = await withTimeout(
        supabase
          .from(TABLE_FOR_ROLE[role])
          .select("*")
          .eq("auth_id", userId)
          .maybeSingle(),
      );
      setProfile((data as Profile) ?? null);
      setProfileForUserId(userId);
    } catch {
      setProfile(null);
      setProfileError(true);
      // Deliberately do NOT set profileForUserId here — a failed fetch
      // leaves the profile "not ready for this user" rather than resolved.
    } finally {
      setProfileLoading(false);
    }
  };

  useEffect(() => {
    // Set synchronously, before the deferred fetch, so a render in
    // between (e.g. the session resolving on the next macrotask) still
    // sees profileLoading=true instead of the previous user's stale value.
    setProfileLoading(true);
    const timer = window.setTimeout(() => void loadProfile(), 0);
    return () => window.clearTimeout(timer);
    // loadProfile is intentionally keyed by the authenticated identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, role]);

  const profileReady = !profileLoading && profileForUserId === userId && !profileError;

  const value: AuthContextValue = {
    session,
    role,
    clinicId,
    profile,
    profileLoading: !profileReady,
    loading,
    refreshProfile: loadProfile,
    signOut: async () => {
      await supabase.auth.signOut();
      setProfile(null);
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() must be used inside <AuthProvider>");
  return ctx;
}
