"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, PageHeader, Pill, Skeleton } from "@/components/ui";
import { useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

interface AppointmentRow {
  id: string;
  slot: string;
  status: "booked" | "cancelled" | "done";
  patients: { name: string } | null;
}

/**
 * Read-only for the MVP by design: the product spec asks for "view
 * appointments booked with them," not doctor-side cancellation. RLS's
 * appointments_select policy already scopes this to the caller's own
 * doctor_id — nothing here does that filtering.
 */
export function AppointmentsTab() {
  const { t, lang } = useLang();
  const [appointments, setAppointments] = useState<AppointmentRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const { data } = await supabase
        .from("appointments")
        .select("id, slot, status, patients(name)")
        .order("slot", { ascending: true });
      setAppointments((data as unknown as AppointmentRow[]) ?? []);
      setLoading(false);
    })();
  }, []);

  return (
    <div>
      <PageHeader eyebrow={t("roleDoctor")} title={t("appointmentsWithMe")} description={t("verifiedKnowledge")} />
      {loading ? <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-20" /></div> : appointments.length === 0 ? <EmptyState icon="calendar" title={t("noAppointmentsYet")} /> : <div className="grid gap-3 lg:grid-cols-2">
      {appointments.map((appt) => (
        <Card key={appt.id} className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <p className="font-bold text-sm">{appt.patients?.name ?? "—"}</p>
            <p className="text-xs text-[var(--ink-soft)]">
              {new Date(appt.slot).toLocaleString(lang === "ar" ? "ar-EG" : "en-US")}
            </p>
          </div>
          <Pill tone={appt.status === "booked" ? "ok" : appt.status === "cancelled" ? "danger" : "neutral"}>
            {appt.status === "booked" ? t("booked") : appt.status === "cancelled" ? t("cancelled") : appt.status}
          </Pill>
        </Card>
      ))}
      </div>}
    </div>
  );
}
