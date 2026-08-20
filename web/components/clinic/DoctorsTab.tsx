"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, ErrorText, Field, PageHeader, Pill, PrimaryButton, SecondaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";

interface DoctorRow {
  id: string;
  name: string;
  specialty: string;
  email: string | null;
  status: "available" | "off";
}

/**
 * Rebuilt, not just kept as-is: the old version was a bare
 * `supabase.from('doctors').insert(...)` — a directory entry with no way
 * to ever log in, since doctors didn't have accounts at all before this
 * role model existed. Adding a doctor now means minting a real Auth user
 * (name/email/password), which needs the service role, so this goes
 * through the backend the same way patient registration already did.
 */
export function DoctorsTab() {
  const { t } = useLang();
  const { session } = useAuth();
  const [doctors, setDoctors] = useState<DoctorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [justRegistered, setJustRegistered] = useState<{ email: string; password: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await supabase.from("doctors").select("*").order("name");
    if (!error && data) setDoctors(data as DoctorRow[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError("");
    setSubmitting(true);

    const response = await fetch(`${API_BASE_URL}/auth/register-doctor`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({ name, email, password, specialty: specialty || "General" }),
    });

    setSubmitting(false);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      setError(body?.detail ?? t("error"));
      return;
    }

    setJustRegistered({ email, password });
    setName("");
    setEmail("");
    setPassword("");
    setSpecialty("");
    setFormOpen(false);
    load();
  }

  async function toggleStatus(doctor: DoctorRow) {
    const next = doctor.status === "available" ? "off" : "available";
    const { error } = await supabase.from("doctors").update({ status: next }).eq("id", doctor.id);
    if (!error) {
      setDoctors((prev) => prev.map((d) => (d.id === doctor.id ? { ...d, status: next } : d)));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={t("roleAdmin")} title={t("doctors")} description={t("clinicLink")} />
      {!formOpen ? (
        <PrimaryButton onClick={() => { setFormOpen(true); setJustRegistered(null); }} className="self-start">
          {t("addDoctor")}
        </PrimaryButton>
      ) : (
        <Card>
          <form onSubmit={handleAdd} className="flex flex-col gap-3">
            <Field label={t("doctorName")}>
              <TextInput required value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t("email")}>
              <TextInput type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label={t("password")}>
              <TextInput type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Field label={t("specialty")}>
              <TextInput value={specialty} onChange={(e) => setSpecialty(e.target.value)} />
            </Field>
            <ErrorText>{error}</ErrorText>
            <div className="flex gap-2">
              <PrimaryButton type="submit" disabled={submitting}>
                {submitting ? t("uploading") : t("add")}
              </PrimaryButton>
              <SecondaryButton type="button" onClick={() => setFormOpen(false)} disabled={submitting}>
                {t("cancelAction")}
              </SecondaryButton>
            </div>
          </form>
        </Card>
      )}

      {justRegistered && (
        <Card className="border-[var(--accent-2)]">
          <p className="text-sm font-semibold">{t("initialPasswordNotice")}</p>
          <p className="text-xs text-[var(--ink-soft)] mt-2">{t("email")}: {justRegistered.email}</p>
          <p className="text-xs text-[var(--ink-soft)]">{t("password")}: {justRegistered.password}</p>
        </Card>
      )}

      {loading ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>
      ) : doctors.length === 0 ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("noDoctorsYet")}</p>
      ) : (
        <div className="flex flex-col gap-2">
          {doctors.map((doctor) => (
            <Card key={doctor.id} className="flex items-center justify-between gap-3">
              <div>
                <p className="font-bold text-sm">{doctor.name}</p>
                <p className="text-xs text-[var(--ink-soft)]">{doctor.specialty}</p>
              </div>
              <button onClick={() => toggleStatus(doctor)}>
                <Pill tone={doctor.status === "available" ? "ok" : "neutral"}>
                  {doctor.status === "available" ? t("available") : t("unavailable")}
                </Pill>
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
