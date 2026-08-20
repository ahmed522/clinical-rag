"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { ErrorText, Field, PrimaryButton, TextInput } from "@/components/ui";
import { establishSession, navigateToRole, type AuthTokenResponse } from "@/lib/auth-api";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";
import { withTimeout } from "@/lib/timeout";

export default function RegisterClinicPage() {
  const { t } = useLang();
  const [clinicName, setClinicName] = useState(""); const [specialty, setSpecialty] = useState("");
  const [adminEmail, setAdminEmail] = useState(""); const [password, setPassword] = useState("");
  const [ownerName, setOwnerName] = useState(""); const [ownerPhone, setOwnerPhone] = useState(""); const [ownerEmail, setOwnerEmail] = useState("");
  const [error, setError] = useState(""); const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault(); setError(""); setSubmitting(true);
    try {
      const response = await withTimeout(fetch(`${API_BASE_URL}/auth/register-clinic`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clinic_name: clinicName, specialty: specialty || "General", admin_email: adminEmail, admin_password: password, owner_name: ownerName || null, owner_phone: ownerPhone || null, owner_email: ownerEmail || null }) }), 20_000);
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail ?? t("error")); }
      const session = await establishSession((await response.json()) as AuthTokenResponse);
      navigateToRole(session.user.app_metadata?.role);
    } catch (cause) { setError(cause instanceof Error && !cause.message.includes("too long") ? cause.message : t("connectionError")); }
    finally { setSubmitting(false); }
  }

  return <AuthShell title={t("registerClinic")} subtitle={t("loginSubtitle")}>
    <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-2"><Field label={t("clinicName")}><TextInput required value={clinicName} onChange={(event) => setClinicName(event.target.value)} /></Field><Field label={t("specialty")}><TextInput value={specialty} onChange={(event) => setSpecialty(event.target.value)} /></Field><div className="sm:col-span-2"><Field label={t("adminEmail")}><TextInput type="email" required value={adminEmail} onChange={(event) => setAdminEmail(event.target.value)} autoComplete="email" /></Field></div><div className="sm:col-span-2"><Field label={t("password")}><TextInput type="password" required minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" /></Field></div><div className="sm:col-span-2 border-t border-[var(--border)] pt-4"><p className="text-xs font-bold uppercase tracking-[0.13em] text-[var(--accent)]">{t("clinicOwner")}</p><p className="mt-1 text-xs text-[var(--ink-faint)]">{t("ownerContactHint")}</p></div><Field label={t("ownerName")}><TextInput value={ownerName} onChange={(event) => setOwnerName(event.target.value)} /></Field><Field label={t("ownerPhone")}><TextInput value={ownerPhone} onChange={(event) => setOwnerPhone(event.target.value)} /></Field><div className="sm:col-span-2"><Field label={t("ownerEmail")}><TextInput type="email" value={ownerEmail} onChange={(event) => setOwnerEmail(event.target.value)} /></Field></div><div className="sm:col-span-2"><ErrorText>{error}</ErrorText><PrimaryButton type="submit" disabled={submitting} className="mt-2 w-full">{submitting ? t("signingIn") : t("createClinic")}</PrimaryButton></div></form>
    <p className="mt-6 text-center text-sm text-[var(--ink-soft)]">{t("alreadyHaveAccount")} <Link href="/login" className="font-extrabold text-[var(--accent)] hover:underline">{t("login")}</Link></p>
  </AuthShell>;
}
