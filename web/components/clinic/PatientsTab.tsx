"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, ErrorText, Field, PrimaryButton, SecondaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";

interface PatientRow {
  id: string;
  name: string;
  age: number | null;
  phone: string | null;
}

export function PatientsTab() {
  const { t } = useLang();
  const { session } = useAuth();
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

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error: fetchError } = await supabase.from("patients").select("*").order("name");
    if (!fetchError && data) setPatients(data as PatientRow[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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

    setName("");
    setEmail("");
    setPassword("");
    setAge("");
    setPhone("");
    setFormOpen(false);
    load();
  }

  return (
    <div className="flex flex-col gap-4">
      {!formOpen ? (
        <PrimaryButton onClick={() => setFormOpen(true)} className="self-start">
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

      {loading ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>
      ) : patients.length === 0 ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("noPatientsYet")}</p>
      ) : (
        <div className="flex flex-col gap-2">
          {patients.map((patient) => (
            <Card key={patient.id} className="flex items-center justify-between gap-3">
              <p className="font-bold text-sm">{patient.name}</p>
              <p className="text-xs text-[var(--ink-soft)]">
                {patient.age ? `${patient.age}` : ""} {patient.phone ?? ""}
              </p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
