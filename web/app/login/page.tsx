"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorText, Field, PrimaryButton, TextInput } from "@/components/ui";
import { supabase } from "@/lib/supabase";
import { useLang } from "@/lib/i18n";

export default function LoginPage() {
  const { t } = useLang();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    const { data, error: signInError } = await supabase.auth.signInWithPassword({ email, password });
    setSubmitting(false);
    if (signInError || !data.session) {
      setError(t("invalidCredentials"));
      return;
    }
    const role = data.session.user.app_metadata?.role;
    router.replace(role === "clinic_admin" ? "/clinic" : "/patient");
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="text-center">
          <h1 className="text-2xl font-extrabold text-[var(--accent)]">{t("appName")}</h1>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] p-6">
          <Field label={t("email")}>
            <TextInput type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </Field>
          <Field label={t("password")}>
            <TextInput type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </Field>
          <ErrorText>{error}</ErrorText>
          <PrimaryButton type="submit" disabled={submitting}>
            {submitting ? t("signingIn") : t("login")}
          </PrimaryButton>
        </form>

        <p className="text-center text-sm text-[var(--ink-soft)]">
          {t("needClinic")}{" "}
          <Link href="/register-clinic" className="font-bold text-[var(--accent)]">
            {t("registerClinic")}
          </Link>
        </p>
      </div>
    </div>
  );
}
