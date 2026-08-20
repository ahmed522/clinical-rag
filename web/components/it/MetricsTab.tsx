"use client";

import { useEffect, useState } from "react";

import { Card, MetricCard, PageHeader, Pill, Skeleton } from "@/components/ui";
import { authenticatedFetch } from "@/lib/auth-api";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";

interface EvaluationReport {
  created_at?: string;
  provider?: string;
  llm_model?: string | null;
  prompt_version?: string;
  dataset_size?: number;
  summary?: {
    in_scope?: { total?: number; grounded_answers?: number; valid_citations?: number; exact_citations?: number };
    out_of_scope?: { total?: number; correct_abstentions?: number };
    retrieval?: { recall_at_5?: number; mean_context_precision?: number; mrr?: number };
    claims?: { faithfulness?: number };
    errors?: number;
    latency_ms?: { p95_total?: number };
  };
}

const percent = (value: number, total = 1) => `${Math.round((value / Math.max(total, 1)) * 100)}%`;

export function MetricsTab() {
  const { t, lang } = useLang();
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const response = await authenticatedFetch(`${API_BASE_URL}/it/metrics`);
        if (response.status === 404) { setMissing(true); return; }
        if (response.ok) setReport((await response.json()) as EvaluationReport);
      } catch {
        setMissing(true);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /><Skeleton className="h-28" /></div>;

  const summary = report?.summary;
  const inScope = summary?.in_scope ?? {};
  const outScope = summary?.out_of_scope ?? {};
  const retrieval = summary?.retrieval ?? {};
  const claims = summary?.claims ?? {};

  return (
    <div>
      <PageHeader eyebrow={t("itOperations")} title={t("ragMetricsTitle")} description={t("ragMetricsHint")} />

      {missing || !report ? (
        <Card className="border-dashed"><p className="text-sm text-[var(--ink-soft)]">{t("evaluationUnavailable")}</p></Card>
      ) : (
        <>
          <div className="mb-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label={t("groundedAnswers")} value={percent(inScope.grounded_answers ?? 0, inScope.total ?? 0)} detail={`${inScope.grounded_answers ?? 0}/${inScope.total ?? 0}`} />
            <MetricCard label={t("recallAtFive")} value={percent(retrieval.recall_at_5 ?? 0, inScope.total ?? 0)} tone="blue" />
            <MetricCard label={t("faithfulness")} value={claims.faithfulness != null ? percent(claims.faithfulness * 100, 100) : "—"} tone="ok" />
            <MetricCard label={t("abstentionAccuracy")} value={percent(outScope.correct_abstentions ?? 0, outScope.total ?? 0)} tone="pending" />
          </div>

          <Card className="mb-7">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-extrabold">{t("latestRun")}</h2>
                <p className="mt-1 text-xs text-[var(--ink-faint)]">{report.created_at ? new Date(report.created_at).toLocaleString(lang === "ar" ? "ar-EG" : "en-US") : "—"}</p>
              </div>
              <Pill tone={(summary?.errors ?? 0) === 0 ? "ok" : "pending"}>{(summary?.errors ?? 0) === 0 ? t("clinicalSafe") : `${summary?.errors} ${t("error")}`}</Pill>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <MetricCard label={t("citationValidity")} value={percent(inScope.valid_citations ?? 0, inScope.grounded_answers ?? inScope.total ?? 0)} detail={`${inScope.exact_citations ?? 0} exact`} tone="blue" />
              <MetricCard label={t("contextPrecision")} value={retrieval.mean_context_precision != null ? percent(retrieval.mean_context_precision * 100, 100) : "—"} />
              <MetricCard label={t("latencyP95")} value={summary?.latency_ms?.p95_total != null ? `${Math.round(summary.latency_ms.p95_total)} ms` : "—"} tone="pending" />
            </div>
          </Card>

          <Card>
            <h2 className="font-extrabold">{t("modelAndPrompt")}</h2>
            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex justify-between gap-3 border-b border-[var(--border)] pb-3"><dt className="text-[var(--ink-soft)]">Provider</dt><dd className="font-extrabold">{report.provider ?? "—"}</dd></div>
              <div className="flex justify-between gap-3 border-b border-[var(--border)] pb-3"><dt className="text-[var(--ink-soft)]">Model</dt><dd className="max-w-[60%] truncate font-extrabold">{report.llm_model ?? "—"}</dd></div>
              <div className="flex justify-between gap-3 border-b border-[var(--border)] pb-3"><dt className="text-[var(--ink-soft)]">Prompt</dt><dd className="font-extrabold">{report.prompt_version ?? "—"}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-[var(--ink-soft)]">Dataset</dt><dd className="font-extrabold">{report.dataset_size ?? "—"}</dd></div>
            </dl>
          </Card>
        </>
      )}
    </div>
  );
}
