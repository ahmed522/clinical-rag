"use client";

import { useEffect, useState } from "react";

import { Icon } from "@/components/Icon";
import { Card, MetricCard, PageHeader, Pill, Skeleton } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";

interface DoctorCount { id: string; name: string; count: number; }
interface EvaluationReport {
  report_version?: string;
  created_at?: string;
  provider?: string;
  llm_model?: string | null;
  prompt_version?: string;
  dataset_size?: number;
  summary?: {
    in_scope?: { total?: number; grounded_answers?: number; valid_citations?: number; exact_citations?: number };
    out_of_scope?: { total?: number; correct_abstentions?: number };
    retrieval?: { recall_at_5?: number; mean_context_precision?: number; mrr?: number };
    claims?: { faithfulness?: number; grounded_with_full_citation_coverage?: number; unsupported?: number; overconfident?: number };
    errors?: number;
    latency_ms?: { p50_total?: number; p95_total?: number };
  };
  results?: { id: number; query: string; scope: string; grounded: boolean; abstained: boolean; validation_errors?: string[]; error?: string | null }[];
}

const percent = (value: number, total = 1) => `${Math.round((value / Math.max(total, 1)) * 100)}%`;

export function AnalyticsTab() {
  const { t, lang } = useLang();
  const { session } = useAuth();
  const [doctorCount, setDoctorCount] = useState(0);
  const [patientCount, setPatientCount] = useState(0);
  const [perDoctor, setPerDoctor] = useState<DoctorCount[]>([]);
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [{ data: doctors }, { data: patients }, evaluation] = await Promise.all([
        supabase.from("doctors").select("id, name"),
        supabase.from("patients").select("doctor_id"),
        session ? fetch(`${API_BASE_URL}/evaluation/latest`, { headers: { Authorization: `Bearer ${session.access_token}` } }).then(async (response) => response.ok ? await response.json() : null).catch(() => null) : Promise.resolve(null),
      ]);
      const doctorList = doctors ?? []; const patientList = patients ?? [];
      setDoctorCount(doctorList.length); setPatientCount(patientList.length);
      setPerDoctor(doctorList.map((doctor) => ({ id: doctor.id, name: doctor.name, count: patientList.filter((patient) => patient.doctor_id === doctor.id).length })));
      setReport(evaluation as EvaluationReport | null); setLoading(false);
    })();
  }, [session]);

  if (loading) return <div className="grid gap-4 sm:grid-cols-2"><Skeleton className="h-32" /><Skeleton className="h-32" /><Skeleton className="h-64 sm:col-span-2" /></div>;

  const summary = report?.summary;
  const inScope = summary?.in_scope ?? {};
  const outScope = summary?.out_of_scope ?? {};
  const retrieval = summary?.retrieval ?? {};
  const claims = summary?.claims ?? {};
  const failures = (report?.results ?? []).filter((row) => row.error || row.validation_errors?.length || (row.scope === "in_scope" ? !row.grounded : !row.abstained)).slice(0, 6);

  return <div>
    <PageHeader eyebrow={t("pipelineHealth")} title={t("ragQuality")} description={t("evaluationSubtitle")} />
    <div className="mb-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><MetricCard label={t("totalDoctors")} value={doctorCount} /><MetricCard label={t("totalPatients")} value={patientCount} tone="blue" /><MetricCard label={t("faithfulness")} value={claims.faithfulness != null ? percent(claims.faithfulness * 100, 100) : "—"} tone="ok" /><MetricCard label={t("latencyP95")} value={summary?.latency_ms?.p95_total != null ? `${Math.round(summary.latency_ms.p95_total)} ms` : "—"} tone="pending" /></div>

    {!report ? <Card className="mb-7 flex items-center gap-3 border-dashed"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--pending-bg)] text-[var(--pending)]"><Icon name="chart" size={20} /></span><div><p className="font-extrabold">{t("evaluationUnavailable")}</p><p className="mt-1 text-xs text-[var(--ink-soft)]">python src/evaluate_rag.py --provider configured</p></div></Card> : <>
      <div className="mb-7 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Card><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-extrabold">{t("latestRun")}</h2><p className="mt-1 text-xs text-[var(--ink-faint)]">{report.created_at ? new Date(report.created_at).toLocaleString(lang === "ar" ? "ar-EG" : "en-US") : "—"}</p></div><Pill tone={(summary?.errors ?? 0) === 0 ? "ok" : "pending"}>{(summary?.errors ?? 0) === 0 ? t("clinicalSafe") : `${summary?.errors} ${t("error")}`}</Pill></div><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><MetricCard label={t("groundedAnswers")} value={percent(inScope.grounded_answers ?? 0, inScope.total ?? 0)} detail={`${inScope.grounded_answers ?? 0}/${inScope.total ?? 0}`} /><MetricCard label={t("citationValidity")} value={percent(inScope.valid_citations ?? 0, inScope.grounded_answers ?? inScope.total ?? 0)} detail={`${inScope.exact_citations ?? 0} exact`} tone="blue" /><MetricCard label={t("abstentionAccuracy")} value={percent(outScope.correct_abstentions ?? 0, outScope.total ?? 0)} detail={`${outScope.correct_abstentions ?? 0}/${outScope.total ?? 0}`} tone="ok" /><MetricCard label={t("recallAtFive")} value={percent(retrieval.recall_at_5 ?? 0, inScope.total ?? 0)} /><MetricCard label={t("contextPrecision")} value={retrieval.mean_context_precision != null ? percent(retrieval.mean_context_precision * 100, 100) : "—"} tone="blue" /><MetricCard label="MRR" value={retrieval.mrr?.toFixed(3) ?? "—"} tone="pending" /></div></Card>
        <Card><h2 className="font-extrabold">{t("modelAndPrompt")}</h2><dl className="mt-4 space-y-3 text-sm"><div className="flex justify-between gap-3 border-b border-[var(--border)] pb-3"><dt className="text-[var(--ink-soft)]">Provider</dt><dd className="font-extrabold">{report.provider ?? "—"}</dd></div><div className="flex justify-between gap-3 border-b border-[var(--border)] pb-3"><dt className="text-[var(--ink-soft)]">Model</dt><dd className="max-w-[60%] truncate font-extrabold">{report.llm_model ?? "—"}</dd></div><div className="flex justify-between gap-3 border-b border-[var(--border)] pb-3"><dt className="text-[var(--ink-soft)]">Prompt</dt><dd className="font-extrabold">{report.prompt_version ?? "—"}</dd></div><div className="flex justify-between gap-3"><dt className="text-[var(--ink-soft)]">Dataset</dt><dd className="font-extrabold">{report.dataset_size ?? "—"}</dd></div></dl></Card>
      </div>

      <Card className="mb-7"><div className="mb-4 flex items-center justify-between"><h2 className="font-extrabold">{t("reportFailures")}</h2><Pill tone={failures.length ? "pending" : "ok"}>{failures.length}</Pill></div>{failures.length === 0 ? <p className="rounded-xl bg-[var(--ok-bg)] p-4 text-sm font-bold text-[var(--ok)]">{t("verificationPassed")}</p> : <div className="space-y-2">{failures.map((row) => <div key={row.id} className="rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] p-3"><p className="text-sm font-bold">#{row.id} {row.query}</p><p className="mt-1 text-xs text-[var(--danger)]">{row.error || row.validation_errors?.join(" · ") || (row.scope === "in_scope" ? "Unexpected refusal" : "Unexpected answer")}</p></div>)}</div>}</Card>
    </>}

    <Card><h2 className="mb-4 font-extrabold">{t("patientsPerDoctor")}</h2>{perDoctor.length === 0 ? <p className="text-sm text-[var(--ink-soft)]">{t("noDoctorsYet")}</p> : <div className="space-y-3">{perDoctor.map((doctor) => <div key={doctor.id} className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-xs font-extrabold text-[var(--accent)]">{doctor.name.slice(0, 2).toUpperCase()}</span><p className="flex-1 text-sm font-bold">{doctor.name}</p><span className="text-sm font-extrabold text-[var(--accent)]">{doctor.count}</span><div className="h-2 w-24 overflow-hidden rounded-full bg-[var(--surface-muted)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${Math.min(100, doctor.count * 12)}%` }} /></div></div>)}</div>}</Card>
  </div>;
}
