"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorText, Field, PrimaryButton, TextInput } from "@/components/ui";
import { API_BASE_URL, supabase } from "@/lib/supabase";
import { useLang } from "@/lib/i18n";

export default function RegisterClinicPage() {
  const { t } = useLang();
  const router = useRouter();
  const [clinicName, setClinicName] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    // Registration has to go through the backend: app_metadata (clinic_id,
    // role) can only be set with the service-role key, which a browser
    // must never hold. Everything after this point talks to Supabase
    // directly — this is the one exception.
    const response = await fetch(`${API_BASE_URL}/auth/register-clinic`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        clinic_name: clinicName,
        specialty: specialty || "General",
        admin_email: adminEmail,
        admin_password: password,
      }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => null);
      setError(body?.detail ?? t("error"));
      setSubmitting(false);
      return;
    }

    // The backend response carries a valid access token, but not a
    // refresh token or client-managed session — signing in properly here
    // gives supabase-js a real session it can keep alive on its own.
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: adminEmail,
      password,
    });
    setSubmitting(false);
    if (signInError) {
      setError(t("invalidCredentials"));
      return;
    }
    router.replace("/clinic");
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="text-center">
          <h1 className="text-2xl font-extrabold text-[var(--accent)]">{t("appName")}</h1>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] p-6">
          <Field label={t("clinicName")}>
            <TextInput required value={clinicName} onChange={(e) => setClinicName(e.target.value)} />
          </Field>
          <Field label={t("specialty")}>
            <TextInput value={specialty} onChange={(e) => setSpecialty(e.target.value)} />
          </Field>
          <Field label={t("adminEmail")}>
            <TextInput type="email" required value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label={t("password")}>
            <TextInput type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </Field>
          <ErrorText>{error}</ErrorText>
          <PrimaryButton type="submit" disabled={submitting}>
            {submitting ? t("signingIn") : t("createClinic")}
          </PrimaryButton>
        </form>

        <p className="text-center text-sm text-[var(--ink-soft)]">
          {t("alreadyHaveAccount")}{" "}
          <Link href="/login" className="font-bold text-[var(--accent)]">
            {t("login")}
          </Link>
        </p>
      </div>
    </div>
  );
}
