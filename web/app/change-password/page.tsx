"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { ErrorText, Field, PrimaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

const TABLE_FOR_ROLE: Record<string, string> = { doctor: "doctors", patient: "patients" };

/**
 * Shared by doctor and patient first-login. Deliberately NOT wrapped in
 * RequireRole — that component redirects HERE when must_change_password
 * is set, so gating this page the same way would loop. The only guard
 * needed is "is anyone signed in at all."
 */
export default function ChangePasswordPage() {
  const { t } = useLang();
  const router = useRouter();
  const { session, role, loading, refreshProfile } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && !session) router.replace("/login");
  }, [loading, session, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError(t("passwordMismatch"));
      return;
    }
    setSubmitting(true);

    const { error: pwError } = await supabase.auth.updateUser({ password });
    if (pwError) {
      setSubmitting(false);
      setError(pwError.message);
      return;
    }

    const table = role ? TABLE_FOR_ROLE[role] : undefined;
    if (table && session) {
      const { error: clearError } = await supabase
        .from(table)
        .update({ must_change_password: false })
        .eq("auth_id", session.user.id);
      if (clearError) {
        // The Supabase password already changed at this point — leaving
        // must_change_password set would bounce the user straight back
        // here from RequireRole with no explanation. Surface it instead.
        setSubmitting(false);
        setError(clearError.message);
        return;
      }
    }
    await refreshProfile();
    setSubmitting(false);

    if (role === "doctor") router.replace("/doctor");
    else router.replace("/patient"); // RequireRole on /patient handles the welcome-screen redirect next
  }

  return (
    <AuthShell title={t("changePassword")} subtitle={t("mustChangePasswordNotice")}>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Field label={t("newPassword")}>
            <TextInput type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </Field>
          <Field label={t("confirmPassword")}>
            <TextInput type="password" required minLength={8} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
          </Field>
          <ErrorText>{error}</ErrorText>
          <PrimaryButton type="submit" disabled={submitting} className="w-full">
            {submitting ? t("loading") : t("continueAction")}
          </PrimaryButton>
        </form>
    </AuthShell>
  );
}
