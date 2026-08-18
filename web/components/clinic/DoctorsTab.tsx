"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, Field, Pill, PrimaryButton, SecondaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

interface DoctorRow {
  id: string;
  name: string;
  specialty: string;
  status: "available" | "off";
}

export function DoctorsTab() {
  const { t } = useLang();
  const { clinicId } = useAuth();
  const [doctors, setDoctors] = useState<DoctorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [specialty, setSpecialty] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const { data, error } = await supabase.from("doctors").select("*").order("name");
    if (!error && data) setDoctors(data as DoctorRow[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!clinicId) return;
    const { data, error } = await supabase
      .from("doctors")
      .insert({ clinic_id: clinicId, name, specialty: specialty || "General" })
      .select()
      .single();
    if (!error && data) {
      setDoctors((prev) => [...prev, data as DoctorRow].sort((a, b) => a.name.localeCompare(b.name)));
      setName("");
      setSpecialty("");
      setFormOpen(false);
    }
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
      {!formOpen ? (
        <PrimaryButton onClick={() => setFormOpen(true)} className="self-start">
          {t("addDoctor")}
        </PrimaryButton>
      ) : (
        <Card>
          <form onSubmit={handleAdd} className="flex flex-col gap-3">
            <Field label={t("doctorName")}>
              <TextInput required value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t("specialty")}>
              <TextInput value={specialty} onChange={(e) => setSpecialty(e.target.value)} />
            </Field>
            <div className="flex gap-2">
              <PrimaryButton type="submit">{t("add")}</PrimaryButton>
              <SecondaryButton type="button" onClick={() => setFormOpen(false)}>
                {t("cancelAction")}
              </SecondaryButton>
            </div>
          </form>
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
