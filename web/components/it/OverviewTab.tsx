"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, MetricCard, PageHeader, Skeleton } from "@/components/ui";
import { authenticatedFetch } from "@/lib/auth-api";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";

interface ClinicStat {
  clinic_id: string;
  clinic_name: string;
  doctor_count: number;
  patient_count: number;
  document_count: number;
}

export function OverviewTab() {
  const { t } = useLang();
  const [rows, setRows] = useState<ClinicStat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const response = await authenticatedFetch(`${API_BASE_URL}/it/stats`);
        if (!response.ok) throw new Error();
        setRows((await response.json()) as ClinicStat[]);
      } catch {
        setError(t("error"));
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /></div>;

  const totals = rows.reduce(
    (acc, r) => ({ doctors: acc.doctors + r.doctor_count, patients: acc.patients + r.patient_count, documents: acc.documents + r.document_count }),
    { doctors: 0, patients: 0, documents: 0 },
  );

  return (
    <div>
      <PageHeader eyebrow={t("itOperations")} title={t("crossClinicStats")} description={t("crossClinicHint")} />
      {error ? (
        <p className="text-sm font-semibold text-[var(--danger)]">{error}</p>
      ) : (
        <>
          <div className="mb-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label={t("totalClinics")} value={rows.length} />
            <MetricCard label={t("doctorCount")} value={totals.doctors} tone="blue" />
            <MetricCard label={t("patientCount")} value={totals.patients} tone="ok" />
            <MetricCard label={t("documentCount")} value={totals.documents} tone="pending" />
          </div>

          {rows.length === 0 ? (
            <EmptyState icon="chart" title={t("crossClinicStats")} />
          ) : (
            <div className="flex flex-col gap-2">
              {rows.map((row) => (
                <Card key={row.clinic_id} className="flex items-center justify-between gap-3">
                  <p className="min-w-0 flex-1 truncate text-sm font-extrabold text-[var(--ink)]">{row.clinic_name}</p>
                  <div className="flex shrink-0 gap-5 text-center text-xs">
                    <div><p className="text-base font-extrabold text-[var(--accent)]">{row.doctor_count}</p><p className="text-[10px] font-bold text-[var(--ink-faint)]">{t("doctorCount")}</p></div>
                    <div><p className="text-base font-extrabold text-[var(--blue)]">{row.patient_count}</p><p className="text-[10px] font-bold text-[var(--ink-faint)]">{t("patientCount")}</p></div>
                    <div><p className="text-base font-extrabold text-[var(--ink-soft)]">{row.document_count}</p><p className="text-[10px] font-bold text-[var(--ink-faint)]">{t("documentCount")}</p></div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
