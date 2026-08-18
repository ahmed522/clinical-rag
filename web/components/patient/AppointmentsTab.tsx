"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, Field, Pill, PrimaryButton, SecondaryButton, TextInput } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

interface Doctor {
  id: string;
  name: string;
  specialty: string;
  status: "available" | "off";
}

interface Appointment {
  id: string;
  doctor_id: string;
  slot: string;
  status: "booked" | "cancelled" | "done";
}

export function AppointmentsTab() {
  const { t, lang } = useLang();
  const [patientId, setPatientId] = useState<string | null>(null);
  const [clinicId, setClinicId] = useState<string | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [doctorId, setDoctorId] = useState("");
  const [slot, setSlot] = useState("");
  const [booking, setBooking] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    // RLS's patients_select policy already limits this to the caller's own
    // row — this is the caller finding out their own id, not a query that
    // needs a separate authorization check.
    const { data: patientRow } = await supabase.from("patients").select("id, clinic_id").single();
    if (patientRow) {
      setPatientId(patientRow.id);
      setClinicId(patientRow.clinic_id);
    }

    const { data: doctorRows } = await supabase.from("doctors").select("*").order("name");
    if (doctorRows) setDoctors(doctorRows as Doctor[]);

    const { data: apptRows } = await supabase
      .from("appointments")
      .select("*")
      .order("slot", { ascending: true });
    if (apptRows) setAppointments(apptRows as Appointment[]);

    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleBook(e: React.FormEvent) {
    e.preventDefault();
    if (!patientId || !clinicId || !doctorId || !slot) return;
    setBooking(true);
    const { data, error } = await supabase
      .from("appointments")
      .insert({
        clinic_id: clinicId,
        patient_id: patientId,
        doctor_id: doctorId,
        slot: new Date(slot).toISOString(),
      })
      .select()
      .single();
    setBooking(false);
    if (!error && data) {
      setAppointments((prev) => [...prev, data as Appointment].sort((a, b) => a.slot.localeCompare(b.slot)));
      setSlot("");
    }
  }

  async function handleCancel(appointment: Appointment) {
    const { error } = await supabase
      .from("appointments")
      .update({ status: "cancelled" })
      .eq("id", appointment.id);
    if (!error) {
      setAppointments((prev) =>
        prev.map((a) => (a.id === appointment.id ? { ...a, status: "cancelled" } : a))
      );
    }
  }

  const doctorName = (id: string) => doctors.find((d) => d.id === id)?.name ?? id;

  if (loading) return <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <p className="font-bold text-sm mb-3">{t("bookAppointment")}</p>
        <form onSubmit={handleBook} className="flex flex-col sm:flex-row gap-3 sm:items-end">
          <div className="flex-1">
            <Field label={t("doctors")}>
              <select
                required
                value={doctorId}
                onChange={(e) => setDoctorId(e.target.value)}
                className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-raised)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--accent)]"
              >
                <option value="" disabled>
                  —
                </option>
                {doctors
                  .filter((d) => d.status === "available")
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} — {d.specialty}
                    </option>
                  ))}
              </select>
            </Field>
          </div>
          <div className="flex-1">
            <Field label={t("slotDateTime")}>
              <TextInput type="datetime-local" required value={slot} onChange={(e) => setSlot(e.target.value)} />
            </Field>
          </div>
          <PrimaryButton type="submit" disabled={booking}>
            {t("book")}
          </PrimaryButton>
        </form>
      </Card>

      <div>
        <p className="font-bold text-sm mb-3">{t("yourAppointments")}</p>
        {appointments.length === 0 ? (
          <p className="text-[var(--ink-soft)] text-sm">{t("noAppointmentsYet")}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {appointments.map((appt) => (
              <Card key={appt.id} className="flex items-center justify-between gap-3 flex-wrap">
                <div>
                  <p className="font-bold text-sm">{doctorName(appt.doctor_id)}</p>
                  <p className="text-xs text-[var(--ink-soft)]">
                    {new Date(appt.slot).toLocaleString(lang === "ar" ? "ar-EG" : "en-US")}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Pill tone={appt.status === "booked" ? "ok" : appt.status === "cancelled" ? "danger" : "neutral"}>
                    {appt.status === "booked" ? t("booked") : appt.status === "cancelled" ? t("cancelled") : appt.status}
                  </Pill>
                  {appt.status === "booked" && (
                    <SecondaryButton onClick={() => handleCancel(appt)} className="text-xs px-3 py-1.5">
                      {t("cancel")}
                    </SecondaryButton>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
