"use client";

import { useEffect, useState } from "react";

import { Card, MetricCard, PageHeader, Skeleton } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

interface DoctorCount { id: string; name: string; count: number; }

/**
 * Clinic-wide counts for the receptionist: doctor count, patient count, and
 * patients-per-doctor. RAG/evaluation metrics deliberately do NOT appear
 * here — that is technical data the receptionist role must not see (it moved
 * to the doctor evaluation view and the IT dashboard). Counts come straight
 * from Supabase under the caller's RLS; there is no backend call here.
 */
export function AnalyticsTab() {
  const { t } = useLang();
  const [doctorCount, setDoctorCount] = useState(0);
  const [patientCount, setPatientCount] = useState(0);
  const [perDoctor, setPerDoctor] = useState<DoctorCount[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [{ data: doctors }, { data: patients }] = await Promise.all([
        supabase.from("doctors").select("id, name"),
        supabase.from("patients").select("doctor_id"),
      ]);
      const doctorList = doctors ?? []; const patientList = patients ?? [];
      setDoctorCount(doctorList.length); setPatientCount(patientList.length);
      setPerDoctor(doctorList.map((doctor) => ({ id: doctor.id, name: doctor.name, count: patientList.filter((patient) => patient.doctor_id === doctor.id).length })));
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="grid gap-4 sm:grid-cols-2"><Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-64 sm:col-span-2" /></div>;

  return <div>
    <PageHeader eyebrow={t("clinicPanel")} title={t("analytics")} description={t("crossClinicHint")} />
    <div className="mb-7 grid gap-3 sm:grid-cols-2"><MetricCard label={t("totalDoctors")} value={doctorCount} /><MetricCard label={t("totalPatients")} value={patientCount} tone="blue" /></div>

    <Card><h2 className="mb-4 font-extrabold">{t("patientsPerDoctor")}</h2>{perDoctor.length === 0 ? <p className="text-sm text-[var(--ink-soft)]">{t("noDoctorsYet")}</p> : <div className="space-y-3">{perDoctor.map((doctor) => <div key={doctor.id} className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-xs font-extrabold text-[var(--accent)]">{doctor.name.slice(0, 2).toUpperCase()}</span><p className="flex-1 text-sm font-bold">{doctor.name}</p><span className="text-sm font-extrabold text-[var(--accent)]">{doctor.count}</span><div className="h-2 w-24 overflow-hidden rounded-full bg-[var(--surface-muted)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${Math.min(100, doctor.count * 12)}%` }} /></div></div>)}</div>}</Card>
  </div>;
}
