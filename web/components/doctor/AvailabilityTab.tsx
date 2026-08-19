"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, Field, PageHeader, PrimaryButton, SecondaryButton } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { type DictKey, useLang } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

interface WindowRow {
  id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
}

const DAY_KEYS: DictKey[] = ["daySun", "dayMon", "dayTue", "dayWed", "dayThu", "dayFri", "daySat"];

/**
 * Weekly recurring windows — the patient booking UI (AppointmentsTab)
 * generates concrete bookable slots from these against existing
 * appointments; this table only holds the recurring rule.
 */
export function AvailabilityTab() {
  const { t } = useLang();
  const { clinicId, profile } = useAuth();
  const [windows, setWindows] = useState<WindowRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [day, setDay] = useState("0");
  const [start, setStart] = useState("14:00");
  const [end, setEnd] = useState("18:00");

  const doctorId = profile?.id as string | undefined;

  const load = useCallback(async () => {
    setLoading(true);
    const { data } = await supabase
      .from("doctor_availability")
      .select("*")
      .order("day_of_week")
      .order("start_time");
    setWindows((data as WindowRow[]) ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!clinicId || !doctorId) return;
    const { data, error } = await supabase
      .from("doctor_availability")
      .insert({
        clinic_id: clinicId,
        doctor_id: doctorId,
        day_of_week: Number(day),
        start_time: start,
        end_time: end,
      })
      .select()
      .single();
    if (!error && data) {
      setWindows((prev) =>
        [...prev, data as WindowRow].sort(
          (a, b) => a.day_of_week - b.day_of_week || a.start_time.localeCompare(b.start_time)
        )
      );
    }
  }

  async function handleRemove(id: string) {
    const { error } = await supabase.from("doctor_availability").delete().eq("id", id);
    if (!error) setWindows((prev) => prev.filter((w) => w.id !== id));
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={t("roleDoctor")} title={t("availability")} description={t("slotDateTime")} />
      <Card>
        <form onSubmit={handleAdd} className="flex flex-col sm:flex-row gap-3 sm:items-end">
          <div className="flex-1">
            <Field label={t("dayOfWeek")}>
              <select
                value={day}
                onChange={(e) => setDay(e.target.value)}
                className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-raised)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--accent)] w-full"
              >
                {DAY_KEYS.map((key, i) => (
                  <option key={key} value={i}>
                    {t(key)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="flex-1">
            <Field label={t("startTime")}>
              <input
                type="time"
                required
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-raised)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--accent)] w-full"
              />
            </Field>
          </div>
          <div className="flex-1">
            <Field label={t("endTime")}>
              <input
                type="time"
                required
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-raised)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--accent)] w-full"
              />
            </Field>
          </div>
          <PrimaryButton type="submit">{t("addWindow")}</PrimaryButton>
        </form>
      </Card>

      {loading ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>
      ) : windows.length === 0 ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("noAvailabilityYet")}</p>
      ) : (
        <div className="flex flex-col gap-2">
          {windows.map((w) => (
            <Card key={w.id} className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold">
                {t(DAY_KEYS[w.day_of_week])} · {w.start_time.slice(0, 5)}–{w.end_time.slice(0, 5)}
              </p>
              <SecondaryButton onClick={() => handleRemove(w.id)} className="text-xs px-3 py-1.5">
                {t("cancel")}
              </SecondaryButton>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
