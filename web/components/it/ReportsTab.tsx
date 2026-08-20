"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, PageHeader, Pill, PrimaryButton, SecondaryButton, Skeleton } from "@/components/ui";
import { authenticatedFetch } from "@/lib/auth-api";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";

interface BugReport {
  id: string;
  clinic_id: string;
  document_id: string | null;
  issue: string;
  status: "open" | "investigating" | "resolved";
  created_at: string;
}

const STATUS_TONE: Record<BugReport["status"], "pending" | "blue" | "ok"> = {
  open: "pending",
  investigating: "blue",
  resolved: "ok",
};

export function ReportsTab() {
  const { t, lang } = useLang();
  const [reports, setReports] = useState<BugReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/it/bug-reports`);
      if (!response.ok) throw new Error();
      setReports((await response.json()) as BugReport[]);
    } catch {
      setError(t("error"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function updateStatus(report: BugReport, status: BugReport["status"]) {
    const response = await authenticatedFetch(`${API_BASE_URL}/it/bug-reports/${report.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (response.ok) {
      const updated = (await response.json()) as BugReport;
      setReports((prev) => prev.map((r) => (r.id === report.id ? updated : r)));
    }
  }

  const statusLabel = (status: BugReport["status"]) =>
    status === "open" ? t("statusOpen") : status === "investigating" ? t("statusInvestigating") : t("statusResolved");

  if (loading) return <div className="flex flex-col gap-3"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={t("itOperations")} title={t("bugReportsQueue")} description={t("pipelineTestHint")} />

      {error ? (
        <p className="text-sm font-semibold text-[var(--danger)]">{error}</p>
      ) : reports.length === 0 ? (
        <EmptyState icon="bell" title={t("noBugReports")} />
      ) : (
        <div className="flex flex-col gap-2">
          {reports.map((report) => (
            <Card key={report.id} className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 flex-1 text-sm text-[var(--ink)]">{report.issue}</p>
                <Pill tone={STATUS_TONE[report.status]}>{statusLabel(report.status)}</Pill>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-3 text-[11px] text-[var(--ink-faint)]">
                <div className="flex flex-col gap-0.5">
                  {report.document_id && <span className="font-mono">{t("documentId")}: {report.document_id}</span>}
                  <span>{t("reportedOn")}: {new Date(report.created_at).toLocaleString(lang === "ar" ? "ar-EG" : "en-US")}</span>
                </div>
                <div className="flex gap-2">
                  {report.status === "open" && (
                    <SecondaryButton onClick={() => updateStatus(report, "investigating")} className="text-xs">{t("markInvestigating")}</SecondaryButton>
                  )}
                  {report.status !== "resolved" && (
                    <PrimaryButton onClick={() => updateStatus(report, "resolved")} className="text-xs">{t("markResolved")}</PrimaryButton>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
