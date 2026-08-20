"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, EmptyState, Field, PageHeader, PrimaryButton, SecondaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

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
 * The doctor's view of their own assigned patients: list, history, and
 * adding medical records. Patient REGISTRATION moved to the receptionist —
 * a doctor no longer mints patient accounts — so there is no add-patient
 * form here anymore. RLS's patients_select doctor branch already scopes
 * this list to the caller's own patients; no client filter does that.
 */
export function PatientsTab() {
  const { t, lang } = useLang();
  const { clinicId } = useAuth();
  const [patients, setPatients] = useState<PatientRow[]>([]);
  const [loading, setLoading] = useState(true);

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
    <div className="flex flex-col gap-5">
      <PageHeader eyebrow={t("roleDoctor")} title={t("myPatients")} description={t("medicalHistory")} />

      {loading ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>
      ) : patients.length === 0 ? (
        <EmptyState icon="users" title={t("noPatientsYet")} />
      ) : (
        <div className="flex flex-col gap-3">
          {patients.map((patient) => (
            <Card
              key={patient.id}
              className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between cursor-pointer hover:border-[var(--accent)]"
            >
              <div onClick={() => openHistory(patient)} className="flex-1">
                <p className="font-bold text-[15px]">{patient.name}</p>
                <div className="mt-3 flex flex-wrap gap-2.5 text-xs">
                  <PatientInfo label={t("age")} value={patient.age != null ? String(patient.age) : "-"} />
                  <PatientInfo label={t("phoneNumber")} value={patient.phone || "-"} />
                </div>
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

function PatientInfo({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] px-2.5 py-1.5">
      <span className="font-bold text-[var(--ink-faint)]">{label}</span>
      <span className="font-extrabold text-[var(--ink-soft)]">{value}</span>
    </span>
  );
}
