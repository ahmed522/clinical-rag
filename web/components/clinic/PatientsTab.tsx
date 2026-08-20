"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, EmptyState, ErrorText, Field, PageHeader, PrimaryButton, SecondaryButton, SelectInput, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";

interface PatientRow {
  id: string;
  name: string;
  age: number | null;
  phone: string | null;
  email: string | null;
  doctor_id: string | null;
}

interface DoctorOption {
  id: string;
  name: string;
}

/**
 * Receptionist patient registration.
 *
 * This is the same account-minting flow the doctor used to own, moved to
 * the receptionist and given a doctor picker: every patient is assigned to
 * a doctor at creation (auto when the clinic has one, chosen when it has
 * several). The receptionist can list patients (RLS's patients_select admin
 * branch) but deliberately never sees medical history — that stays with the
 * doctor. No records/history surface exists here by design.
 */
export function PatientsTab() {
  const { t } = useLang();
  const { session, clinicId } = useAuth();
  const [patients, setPatients] = useState<PatientRow[]>([]);
  const [doctors, setDoctors] = useState<DoctorOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [age, setAge] = useState("");
  const [phone, setPhone] = useState("");
  const [doctorId, setDoctorId] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [justRegistered, setJustRegistered] = useState<{ email: string; password: string } | null>(null);
  const [clinicSlug, setClinicSlug] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [{ data: patientData }, { data: doctorData }] = await Promise.all([
      supabase.from("patients").select("id, name, age, phone, email, doctor_id").order("name"),
      supabase.from("doctors").select("id, name").order("name"),
    ]);
    setPatients((patientData as PatientRow[]) ?? []);
    setDoctors((doctorData as DoctorOption[]) ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!clinicId) return;
    supabase
      .from("clinics")
      .select("slug")
      .eq("id", clinicId)
      .maybeSingle()
      .then(({ data }) => setClinicSlug(data?.slug ?? null));
  }, [clinicId]);

  const doctorName = (id: string | null) => doctors.find((d) => d.id === id)?.name ?? "—";
  const needsPicker = doctors.length > 1;

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError("");
    setSubmitting(true);

    // Minting a Supabase Auth user with app_metadata needs the service
    // role, so registration goes through the backend, not a table insert.
    const response = await fetch(`${API_BASE_URL}/auth/register-patient`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        name,
        email,
        password,
        age: age ? Number(age) : null,
        phone: phone || null,
        // Omit when the clinic has a single doctor: the backend auto-assigns.
        doctor_id: needsPicker ? doctorId || null : null,
      }),
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
    setAge("");
    setPhone("");
    setDoctorId("");
    setFormOpen(false);
    load();
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader eyebrow={t("roleAdmin")} title={t("patients")} description={t("crossClinicHint")} />

      {doctors.length === 0 && !loading ? (
        <Card className="border-[var(--pending)]/40 bg-[var(--pending-bg)]">
          <p className="text-sm text-[var(--ink-soft)]">{t("registerFirstDoctor")}</p>
        </Card>
      ) : !formOpen ? (
        <PrimaryButton onClick={() => { setFormOpen(true); setJustRegistered(null); }} className="self-start">
          {t("addPatient")}
        </PrimaryButton>
      ) : (
        <Card>
          <form onSubmit={handleAdd} className="flex flex-col gap-3">
            <Field label={t("patientName")}>
              <TextInput required value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t("email")}>
              <TextInput type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label={t("password")}>
              <TextInput type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("age")}>
                <TextInput type="number" min={0} max={130} value={age} onChange={(e) => setAge(e.target.value)} />
              </Field>
              <Field label={t("phone")}>
                <TextInput value={phone} onChange={(e) => setPhone(e.target.value)} />
              </Field>
            </div>
            {needsPicker && (
              <Field label={t("assignDoctor")}>
                <SelectInput required value={doctorId} onChange={(e) => setDoctorId(e.target.value)}>
                  <option value="" disabled>{t("selectDoctor")}</option>
                  {doctors.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </SelectInput>
              </Field>
            )}
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
          {clinicSlug && (
            <p className="text-xs text-[var(--ink-soft)] mt-1">
              {t("clinicLink")}: {typeof window !== "undefined" ? window.location.origin : ""}/clinic/{clinicSlug}
            </p>
          )}
        </Card>
      )}

      {loading ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>
      ) : patients.length === 0 ? (
        <EmptyState icon="users" title={t("noPatientsYet")} />
      ) : (
        <div className="flex flex-col gap-3">
          {patients.map((patient) => (
            <Card key={patient.id} className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="font-bold text-sm">{patient.name}</p>
                <div className="mt-3 flex flex-wrap gap-2.5">
                  <PatientInfo label={t("age")} value={patient.age != null ? String(patient.age) : "—"} />
                  <PatientInfo label={t("phoneNumber")} value={patient.phone || "—"} />
                </div>
              </div>
              <div className="shrink-0 rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] px-3.5 py-2 text-xs text-[var(--ink-soft)]">
                {t("assignDoctor")}: <span className="font-bold text-[var(--ink-soft)]">{doctorName(patient.doctor_id)}</span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function PatientInfo({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] px-2.5 py-1.5 text-xs">
      <span className="font-bold text-[var(--ink-faint)]">{label}</span>
      <span className="font-extrabold text-[var(--ink-soft)]">{value}</span>
    </span>
  );
}
