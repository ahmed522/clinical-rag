"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { ErrorText, Field, PrimaryButton, TextInput } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";
import { withTimeout } from "@/lib/timeout";

interface ClinicPublic {
  id: string;
  name: string;
  slug: string;
}

/**
 * Patient entry point — separated from the general /login by URL, not by
 * a role picker, per the product decision that patients should never be
 * asked to choose between internal roles. The clinic is resolved from the
 * URL itself via the one deliberately public backend lookup
 * (GET /clinics/by-slug/{slug} — see app/routers/clinics.py).
 *
 * After a successful sign-in, the authenticated account's OWN clinic_id
 * (from its JWT, never client-editable) is compared against this slug's
 * clinic_id. A mismatch is rejected with a clear error rather than
 * silently landing the patient somewhere else — RLS would already prevent
 * any actual cross-tenant data access, but a patient on the wrong clinic's
 * link deserves to know that plainly, not a confusing dead end.
 */
export default function ClinicLoginPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const { t } = useLang();
  const router = useRouter();

  const [clinic, setClinic] = useState<ClinicPublic | null>(null);
  const [clinicLoading, setClinicLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    withTimeout(fetch(`${API_BASE_URL}/clinics/by-slug/${encodeURIComponent(slug)}`))
      .then(async (res) => (res.ok ? ((await res.json()) as ClinicPublic) : null))
      .then(setClinic)
      .catch(() => setClinic(null))
      .finally(() => setClinicLoading(false));
  }, [slug]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!clinic) return;
    setError("");
    setSubmitting(true);

    try {
      const { data, error: signInError } = await withTimeout(
        supabase.auth.signInWithPassword({ email, password }),
      );
      if (signInError || !data.session) {
        setError(t("invalidCredentials"));
        return;
      }

      const role = data.session.user.app_metadata?.role;
      const accountClinicId = data.session.user.app_metadata?.clinic_id;

      if (role === "patient" && accountClinicId !== clinic.id) {
        await withTimeout(supabase.auth.signOut());
        setError(t("wrongClinicError"));
        return;
      }

      if (role === "clinic_admin") router.replace("/clinic");
      else if (role === "doctor") router.replace("/doctor");
      else router.replace("/patient");
    } catch {
      setError(t("connectionError"));
    } finally {
      setSubmitting(false);
    }
  }

  if (clinicLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[var(--ink-soft)]">
        {t("loading")}
      </div>
    );
  }

  if (!clinic) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[var(--ink-soft)]">
        {t("clinicNotFound")}
      </div>
    );
  }

  return (
    <AuthShell title={t("login")} subtitle={t("loginSubtitle")} clinicName={clinic.name}>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Field label={t("email")}>
            <TextInput type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label={t("password")}>
            <TextInput type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </Field>
          <ErrorText>{error}</ErrorText>
          <PrimaryButton type="submit" disabled={submitting} className="w-full">
            {submitting ? t("signingIn") : t("login")}
          </PrimaryButton>
        </form>
    </AuthShell>
  );
}
