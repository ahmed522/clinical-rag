"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, ErrorText, Field, PageHeader, PrimaryButton, SecondaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";

interface PatientRow {
  id: string;
  name: string;
  age: number | null;
  phone: string | null;
  email: string | null;
}

interface RecordRow {
  id: string;
  diagnosis: string | null;
  notes: string | null;
  created_at: string;
}

/**
 * Rebuilt, not just relocated, from the old clinic-admin version: patient
 * registration moved from a plain table insert to minting a real Auth
 * account (name/email/password), and RLS's patients_doctor_insert policy
 * means this list is already scoped to the caller's OWN patients — no
 * client-side filter does that, the database does.
 */
export function PatientsTab() {
  const { t, lang } = useLang();
  const { session, clinicId } = useAuth();
  const [patients, setPatients] = useState<PatientRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [age, setAge] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [justRegistered, setJustRegistered] = useState<{ email: string; password: string } | null>(null);
  const [clinicSlug, setClinicSlug] = useState<string | null>(null);

  const [selected, setSelected] = useState<PatientRow | null>(null);
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordFormOpen, setRecordFormOpen] = useState(false);
  const [diagnosis, setDiagnosis] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error: fetchError } = await supabase.from("patients").select("*").order("name");
    if (!fetchError && data) setPatients(data as PatientRow[]);
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

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!session) return;
    setError("");
    setSubmitting(true);

    // Registering a patient means minting a Supabase Auth user with
    // app_metadata set — only the service role can do that, so this one
    // goes through the backend rather than a direct table insert.
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
    setFormOpen(false);
    load();
  }

  async function openHistory(patient: PatientRow) {
    setSelected(patient);
    setRecordsLoading(true);
    const { data } = await supabase
      .from("medical_records")
      .select("*")
      .eq("patient_id", patient.id)
      .order("created_at", { ascending: false });
    setRecords((data as RecordRow[]) ?? []);
    setRecordsLoading(false);
  }

  async function handleAddRecord(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || !clinicId) return;
    const { data, error: insertError } = await supabase
      .from("medical_records")
      .insert({ clinic_id: clinicId, patient_id: selected.id, diagnosis, notes })
      .select()
      .single();
    if (!insertError && data) {
      setRecords((prev) => [data as RecordRow, ...prev]);
      setDiagnosis("");
      setNotes("");
      setRecordFormOpen(false);
    }
  }

  if (selected) {
    return (
      <div className="flex flex-col gap-4">
        <button
          onClick={() => setSelected(null)}
          className="self-start text-sm font-semibold text-[var(--accent)]"
        >
          ← {t("backToPatients")}
        </button>
        <div>
          <p className="font-bold text-lg">{selected.name}</p>
          <p className="text-sm text-[var(--ink-soft)]">
            {selected.age ? `${selected.age} · ` : ""}
            {selected.phone ?? ""}
          </p>
        </div>

        <p className="font-bold text-sm mt-2">{t("medicalHistory")}</p>

        {!recordFormOpen ? (
          <PrimaryButton onClick={() => setRecordFormOpen(true)} className="self-start text-xs px-3 py-1.5">
            {t("addRecord")}
          </PrimaryButton>
        ) : (
          <Card>
            <form onSubmit={handleAddRecord} className="flex flex-col gap-3">
              <Field label={t("diagnosis")}>
                <TextInput required value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)} />
              </Field>
              <Field label={t("notes")}>
                <TextInput value={notes} onChange={(e) => setNotes(e.target.value)} />
              </Field>
              <div className="flex gap-2">
                <PrimaryButton type="submit">{t("add")}</PrimaryButton>
                <SecondaryButton type="button" onClick={() => setRecordFormOpen(false)}>
                  {t("cancelAction")}
                </SecondaryButton>
              </div>
            </form>
          </Card>
        )}

        {recordsLoading ? (
          <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>
        ) : records.length === 0 ? (
          <p className="text-[var(--ink-soft)] text-sm">{t("noRecordsYet")}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {records.map((r) => (
              <Card key={r.id}>
                <p className="font-bold text-sm">{r.diagnosis || "—"}</p>
                {r.notes && <p className="text-sm text-[var(--ink-soft)] mt-1">{r.notes}</p>}
                <p className="text-[11px] text-[var(--ink-faint)] mt-2">
                  {new Date(r.created_at).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US")}
                </p>
              </Card>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={t("roleDoctor")} title={t("myPatients")} description={t("medicalHistory")} />
      {!formOpen ? (
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
        <p className="text-[var(--ink-soft)] text-sm">{t("noPatientsYet")}</p>
      ) : (
        <div className="flex flex-col gap-2">
          {patients.map((patient) => (
            <Card
              key={patient.id}
              className="flex items-center justify-between gap-3 cursor-pointer hover:border-[var(--accent)]"
            >
              <div onClick={() => openHistory(patient)} className="flex-1">
                <p className="font-bold text-sm">{patient.name}</p>
                <p className="text-xs text-[var(--ink-soft)]">
                  {patient.age ? `${patient.age}` : ""} {patient.phone ?? ""}
                </p>
              </div>
              <SecondaryButton onClick={() => openHistory(patient)} className="text-xs px-3 py-1.5">
                {t("viewHistory")}
              </SecondaryButton>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
