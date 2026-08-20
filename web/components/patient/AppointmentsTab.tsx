"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Card, ErrorText, Field, PageHeader, Pill, PrimaryButton, SecondaryButton } from "@/components/ui";
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

interface AvailabilityWindow {
  doctor_id: string;
  day_of_week: number;
  start_time: string; // "HH:MM:SS"
  end_time: string;
}

const SLOT_MINUTES = 30;
const DAYS_AHEAD = 14;

/**
 * Generates concrete bookable slots from the doctor's weekly recurring
 * windows (doctor_availability) — that table holds only the recurring
 * rule, not materialized slots.
 *
 * This deliberately does NOT try to exclude slots other patients already
 * booked: RLS's appointments_select scopes a patient to only their OWN
 * appointments (by design — one patient can't see another's booking
 * history), so there is no privacy-safe way to know a doctor's full
 * schedule client-side. Instead, booking is optimistic: the attempt goes
 * to Postgres, and idx_appointments_doctor_slot's unique constraint
 * rejects a real conflict, which the UI surfaces as "just taken, pick
 * another" rather than silently failing.
 */
function generateSlots(windows: AvailabilityWindow[], doctorId: string): Date[] {
  const doctorWindows = windows.filter((w) => w.doctor_id === doctorId);
  if (doctorWindows.length === 0) return [];

  const slots: Date[] = [];
  const now = new Date();

  for (let dayOffset = 0; dayOffset < DAYS_AHEAD; dayOffset++) {
    const day = new Date(now);
    day.setDate(day.getDate() + dayOffset);
    const weekday = day.getDay();

    for (const w of doctorWindows) {
      if (w.day_of_week !== weekday) continue;
      const [startH, startM] = w.start_time.split(":").map(Number);
      const [endH, endM] = w.end_time.split(":").map(Number);

      const cursor = new Date(day);
      cursor.setHours(startH, startM, 0, 0);
      const end = new Date(day);
      end.setHours(endH, endM, 0, 0);

      while (cursor < end) {
        if (cursor > now) slots.push(new Date(cursor));
        cursor.setMinutes(cursor.getMinutes() + SLOT_MINUTES);
      }
    }
  }

  return slots.sort((a, b) => a.getTime() - b.getTime());
}

export function AppointmentsTab() {
  const { t, lang } = useLang();
  const [patientId, setPatientId] = useState<string | null>(null);
  const [clinicId, setClinicId] = useState<string | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [windows, setWindows] = useState<AvailabilityWindow[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [doctorId, setDoctorId] = useState("");
  const [slotIso, setSlotIso] = useState("");
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState("");

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

    const [{ data: doctorRows }, { data: windowRows }, { data: apptRows }] = await Promise.all([
      supabase.from("doctors").select("*").order("name"),
      supabase.from("doctor_availability").select("doctor_id, day_of_week, start_time, end_time"),
      supabase.from("appointments").select("*").order("slot", { ascending: true }),
    ]);
    if (doctorRows) setDoctors(doctorRows as Doctor[]);
    if (windowRows) setWindows(windowRows as AvailabilityWindow[]);
    if (apptRows) setAppointments(apptRows as Appointment[]);

    setLoading(false);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const slots = useMemo(() => (doctorId ? generateSlots(windows, doctorId) : []), [windows, doctorId]);

  async function handleBook(e: React.FormEvent) {
    e.preventDefault();
    if (!patientId || !clinicId || !doctorId || !slotIso) return;
    setError("");
    setBooking(true);
    const { data, error: insertError } = await supabase
      .from("appointments")
      .insert({ clinic_id: clinicId, patient_id: patientId, doctor_id: doctorId, slot: slotIso })
      .select()
      .single();
    setBooking(false);
    if (insertError) {
      // 23505 = unique_violation — idx_appointments_doctor_slot caught a
      // real double-booking race, not a client bug.
      setError(insertError.code === "23505" ? t("error") : insertError.message);
      return;
    }
    if (data) {
      setAppointments((prev) => [...prev, data as Appointment].sort((a, b) => a.slot.localeCompare(b.slot)));
      setSlotIso("");
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
      <PageHeader eyebrow={t("rolePatient")} title={t("appointments")} description={t("bookAppointment")} />
      <Card>
        <p className="font-bold text-sm mb-3">{t("bookAppointment")}</p>
        <form onSubmit={handleBook} className="flex flex-col sm:flex-row gap-3 sm:items-end">
          <div className="flex-1">
            <Field label={t("doctors")}>
              <select
                required
                value={doctorId}
                onChange={(e) => {
                  setDoctorId(e.target.value);
                  setSlotIso("");
                }}
                className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-raised)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--accent)] w-full"
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
              <select
                required
                disabled={!doctorId}
                value={slotIso}
                onChange={(e) => setSlotIso(e.target.value)}
                className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-raised)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--accent)] w-full disabled:opacity-50"
              >
                <option value="" disabled>
                  —
                </option>
                {slots.map((s) => (
                  <option key={s.toISOString()} value={s.toISOString()}>
                    {s.toLocaleString(lang === "ar" ? "ar-EG" : "en-US", {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <PrimaryButton type="submit" disabled={booking || !slotIso}>
            {t("book")}
          </PrimaryButton>
        </form>
        <ErrorText>{error}</ErrorText>
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
