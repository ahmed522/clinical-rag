"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { ErrorText, Field, PrimaryButton, TextInput } from "@/components/ui";
import { loginWithApi, navigateToRole } from "@/lib/auth-api";
import { useLang } from "@/lib/i18n";

export default function LoginPage() {
  const { t } = useLang();
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [error, setError] = useState(""); const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault(); setError(""); setSubmitting(true);
    try {
      const session = await loginWithApi(email, password);
      navigateToRole(session.user.app_metadata?.role);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message.toLowerCase() : "";
      setError(
        message.includes("incorrect") || message.includes("invalid login")
          ? t("invalidCredentials")
          : t("connectionError"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return <AuthShell title={t("login")} subtitle={t("loginSubtitle")}>
    <form onSubmit={handleSubmit} className="auth-login-form space-y-5"><Field label={t("email")}><TextInput type="email" required value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" /></Field><Field label={t("password")}><TextInput type="password" required value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></Field><ErrorText>{error}</ErrorText><PrimaryButton type="submit" disabled={submitting} className="w-full">{submitting ? t("signingIn") : t("login")}</PrimaryButton></form>
    <p className="mt-7 text-center text-sm text-[var(--ink-soft)]">{t("needClinic")} <Link href="/register-clinic" className="font-extrabold text-[var(--accent)] underline-offset-4 hover:underline">{t("registerClinic")}</Link></p>
  </AuthShell>;
}
