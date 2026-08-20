"use client";

import { useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/Icon";
import { authenticatedFetch } from "@/lib/auth-api";
import { API_BASE_URL } from "@/lib/supabase";

type Action = "book" | "cancel" | "reschedule";

interface Doctor { id: string; name: string; specialty?: string | null; }
interface Slot { doctor_id: string; slot: string; }
interface Appointment { id: string; doctor_id: string; slot: string; status: string; doctor_name?: string | null; }
interface Options { doctors: Doctor[]; slots: Slot[]; appointments: Appointment[]; }

export function AppointmentChatAction({ action, sessionId, onComplete }: { action: Action; sessionId: string; onComplete: (message: unknown) => void }) {
  const [options, setOptions] = useState<Options | null>(null);
  const [doctorId, setDoctorId] = useState("");
  const [slot, setSlot] = useState("");
  const [appointmentId, setAppointmentId] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void authenticatedFetch(`${API_BASE_URL}/chat/appointment-options`).then(async (response) => {
      if (!response.ok) throw new Error("Unable to load appointment options.");
      const data = await response.json() as Options;
      if (active) setOptions(data);
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Unable to load appointment options."); });
    return () => { active = false; };
  }, []);

  const selectedAppointment = options?.appointments.find((item) => item.id === appointmentId);
  const selectedDoctorId = action === "reschedule" ? doctorId || selectedAppointment?.doctor_id || "" : doctorId;
  const slots = useMemo(() => (options?.slots ?? []).filter((item) => item.doctor_id === selectedDoctorId), [options, selectedDoctorId]);
  const requiresTime = action !== "cancel";
  const valid = action === "cancel" ? !!appointmentId : !!selectedDoctorId && !!slot && (action !== "reschedule" || !!appointmentId);
  const actionLabel = action === "book" ? "Book appointment" : action === "cancel" ? "Cancel appointment" : "Reschedule appointment";

  async function confirm() {
    if (!valid) return;
    setConfirming(true); setError("");
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/chat/${sessionId}/appointment-action`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, confirmed: true, doctor_id: selectedDoctorId || undefined, slot: slot || undefined, appointment_id: appointmentId || undefined }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.detail ?? "The appointment could not be updated.");
      onComplete(data.message);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The appointment could not be updated."); }
    finally { setConfirming(false); }
  }

  if (!options && !error) return <div className="self-start rounded-xl border border-[var(--border)] bg-white px-4 py-3 text-sm text-[var(--ink-soft)]">Loading appointment options…</div>;
  return <section className="self-start w-full rounded-2xl border border-[#ded7ef] bg-white p-4 shadow-[var(--shadow-sm)]" aria-label={`${actionLabel} options`}>
    <div className="mb-3 flex items-center gap-2 text-sm font-extrabold text-[var(--ink)]"><Icon name="calendar" size={16} />{actionLabel}</div>
    {error && <p role="alert" className="mb-3 rounded-lg bg-[var(--danger-bg)] p-3 text-xs font-bold text-[var(--danger)]">{error}</p>}
    {options && <div className="grid gap-3 sm:grid-cols-2">
      {action !== "book" && <label className="grid gap-1 text-xs font-bold text-[var(--ink-soft)]">Appointment<select value={appointmentId} onChange={(event) => { setAppointmentId(event.target.value); setSlot(""); }} className="rounded-xl border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--ink)]"><option value="">Choose an appointment</option>{options.appointments.map((item) => <option key={item.id} value={item.id}>{item.doctor_name ? `Dr. ${item.doctor_name}` : "Doctor"} — {new Date(item.slot).toLocaleString("en-US")}</option>)}</select></label>}
      {requiresTime && <label className="grid gap-1 text-xs font-bold text-[var(--ink-soft)]">Doctor<select value={selectedDoctorId} onChange={(event) => { setDoctorId(event.target.value); setSlot(""); }} className="rounded-xl border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--ink)]"><option value="">Choose a doctor</option>{options.doctors.map((doctor) => <option key={doctor.id} value={doctor.id}>Dr. {doctor.name}{doctor.specialty ? ` — ${doctor.specialty}` : ""}</option>)}</select></label>}
      {requiresTime && <label className="grid gap-1 text-xs font-bold text-[var(--ink-soft)]">Available time<select value={slot} disabled={!selectedDoctorId} onChange={(event) => setSlot(event.target.value)} className="rounded-xl border border-[var(--border)] bg-white px-3 py-2 text-sm text-[var(--ink)] disabled:opacity-50"><option value="">Choose a time</option>{slots.map((item) => <option key={item.slot} value={item.slot}>{new Date(item.slot).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</option>)}</select></label>}
    </div>}
    <button type="button" disabled={!valid || confirming} onClick={() => void confirm()} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm font-extrabold text-white disabled:opacity-40"><Icon name="check" size={15} />{confirming ? "Confirming…" : `Confirm ${actionLabel.toLowerCase()}`}</button>
  </section>;
}
