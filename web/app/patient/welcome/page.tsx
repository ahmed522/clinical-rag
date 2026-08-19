"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthShell } from "@/components/AuthShell";
import { Icon } from "@/components/Icon";
import { Field, PrimaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

/**
 * First-time onboarding for a patient, after the forced password change.
 * Not wrapped in RequireRole (which redirects HERE when onboarding isn't
 * complete) — this page's own guard is lighter: signed in, patient role,
 * password already set. Looping back to itself is impossible since it
 * never redirects to itself.
 */
export default function PatientWelcomePage() {
  const { t } = useLang();
  const router = useRouter();
  const { session, role, profile, loading, profileLoading, refreshProfile } = useAuth();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [age, setAge] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [prefilled, setPrefilled] = useState(false);

  useEffect(() => {
    if (loading || profileLoading) return;
    if (!session) {
      router.replace("/login");
      return;
    }
    if (role !== "patient") {
      router.replace("/login");
      return;
    }
    if (profile?.must_change_password) {
      router.replace("/change-password");
    }
  }, [loading, profileLoading, session, role, profile, router]);

  useEffect(() => {
    if (profile && !prefilled) {
      let active = true;
      queueMicrotask(() => {
        if (!active) return;
        setName((profile.name as string) ?? "");
        setPhone((profile.phone as string) ?? "");
        setAge(profile.age ? String(profile.age) : "");
        setPrefilled(true);
      });
      return () => { active = false; };
    }
  }, [profile, prefilled]);

  async function handleContinue(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setSubmitting(true);
    await supabase
      .from("patients")
      .update({
        name,
        phone: phone || null,
        age: age ? Number(age) : null,
        onboarding_completed: true,
      })
      .eq("auth_id", session.user.id);
    await refreshProfile();
    setSubmitting(false);
    router.replace("/patient");
  }

  return (
    <AuthShell title={t("welcomeTitle")} subtitle={t("confirmYourInfo")}>
        <div className="mb-5 grid gap-2 sm:grid-cols-3">
          {[
            ["chat", t("welcomeAskQuestion")],
            ["calendar", t("welcomeBookAppointment")],
            ["file", t("welcomeSeeHistory")],
          ].map(([icon, line]) => (
            <div key={line} className="rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] p-3 text-center">
              <span className="mx-auto mb-2 flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]"><Icon name={icon as "chat" | "calendar" | "file"} size={15} /></span>
              <span className="text-xs font-bold leading-5">{line}</span>
            </div>
          ))}
        </div>
        <div className="mb-5 rounded-xl border border-[#f2cfcc] bg-[var(--danger-bg)] p-3.5 text-xs font-semibold leading-5 text-[var(--danger-ink)]">{t("welcomeSafety")}</div>
        <form onSubmit={handleContinue} className="flex flex-col gap-4">
          <p className="font-bold text-sm">{t("confirmYourInfo")}</p>
          <Field label={t("patientName")}>
            <TextInput required value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("age")}>
              <TextInput type="number" min={0} max={130} value={age} onChange={(e) => setAge(e.target.value)} />
            </Field>
            <Field label={t("phone")}>
              <TextInput value={phone} onChange={(e) => setPhone(e.target.value)} />
            </Field>
          </div>
          <PrimaryButton type="submit" disabled={submitting} className="w-full">
            {submitting ? t("loading") : t("getStarted")}
          </PrimaryButton>
        </form>
    </AuthShell>
  );
}
