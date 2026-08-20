"use client";

import { useEffect, useState } from "react";

import { Icon } from "@/components/Icon";
import { Card, Field, PageHeader, Pill, PrimaryButton, SecondaryButton, TextArea, TextInput } from "@/components/ui";
import { authenticatedFetch } from "@/lib/auth-api";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";

interface StageResult {
  status: string;
  error?: string;
  [key: string]: unknown;
}

interface PipelineResult {
  document: { id: string; title?: string; clinic_id: string; status?: string; verified?: boolean };
  question: string;
  stages: { indexing: StageResult; retrieval: StageResult; generation: StageResult };
}

type StageState = "passed" | "failed" | "not-reached";

/**
 * The Test section: run a doctor's problem document through the pipeline
 * one stage at a time (indexing -> retrieval -> generation -> final output),
 * revealing each step's real output on demand. If a stage fails, the chain
 * is severed and downstream stages read "Not reached" — mirroring how the
 * pipeline actually behaves.
 */
export function PipelineTestTab() {
  const { t } = useLang();
  const [documentId, setDocumentId] = useState("");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [revealed, setRevealed] = useState(0);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    if (!documentId.trim() || !question.trim()) return;
    setLoading(true); setError(""); setResult(null); setRevealed(0);
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/it/pipeline-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: documentId.trim(), question: question.trim() }),
      }, 180_000);
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail ?? t("error")); }
      setResult((await response.json()) as PipelineResult);
      setRevealed(1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("error"));
    } finally {
      setLoading(false);
    }
  }

  // The ordered stage list. "generation" carries both the generation audit
  // and the final answer, so it feeds the last two visual steps.
  const steps = result
    ? [
        { key: "indexing", label: t("stageIndexing"), stage: result.stages.indexing },
        { key: "retrieval", label: t("stageRetrieval"), stage: result.stages.retrieval },
        { key: "generation", label: t("stageGeneration"), stage: result.stages.generation },
        { key: "final", label: t("finalOutput"), stage: result.stages.generation },
      ]
    : [];

  // First failed stage severs the chain: everything after it is "not reached".
  const firstFailure = steps.findIndex((s) => s.stage.status === "error");
  const stateFor = (index: number): StageState => {
    if (firstFailure !== -1 && index > firstFailure) return "not-reached";
    return steps[index].stage.status === "error" ? "failed" : "passed";
  };

  const allRevealed = result != null && revealed >= steps.length;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={t("itOperations")} title={t("pipelineTestTitle")} description={t("pipelineTestHint")} />

      <Card>
        <form onSubmit={run} className="flex flex-col gap-3">
          <Field label={t("documentId")}>
            <TextInput required value={documentId} onChange={(e) => setDocumentId(e.target.value)} placeholder="00000000-0000-0000-0000-000000000000" />
          </Field>
          <Field label={t("testQuestion")}>
            <TextArea required value={question} onChange={(e) => setQuestion(e.target.value)} />
          </Field>
          <PrimaryButton type="submit" disabled={loading || !documentId.trim() || !question.trim()} className="self-start">
            <Icon name="activity" size={16} />{loading ? t("running") : t("runTest")}
          </PrimaryButton>
        </form>
      </Card>

      {error && <p className="text-sm font-semibold text-[var(--danger)]">{error}</p>}

      {result && (
        <div className="flex flex-col gap-3">
          {steps.slice(0, revealed).map((step, index) => (
            <StageCard key={step.key} index={index} label={step.label} state={stateFor(index)} stepKey={step.key} stage={step.stage} />
          ))}

          {!allRevealed && (
            <SecondaryButton onClick={() => setRevealed((r) => r + 1)} className="self-start">
              {t("finalOutput")} →
            </SecondaryButton>
          )}

          {allRevealed && (
            <Card className="flex items-center justify-between gap-3 border-dashed">
              <div className="flex items-center gap-2 text-sm text-[var(--ink-soft)]">
                <Icon name="activity" size={16} />{t("langsmithNotConfigured")}
              </div>
              <span className="cursor-not-allowed rounded-[var(--radius-sm)] border border-[var(--border)] px-3 py-2 text-xs font-bold text-[var(--ink-faint)]">
                {t("langsmithLink")} ↗
              </span>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

const STATE_TONE: Record<StageState, "ok" | "danger" | "neutral"> = {
  passed: "ok",
  failed: "danger",
  "not-reached": "neutral",
};

function StageCard({ index, label, state, stepKey, stage }: { index: number; label: string; state: StageState; stepKey: string; stage: StageResult }) {
  const { t } = useLang();
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setShown(true), 20);
    return () => window.clearTimeout(id);
  }, []);

  const stateLabel = state === "passed" ? t("stagePassed") : state === "failed" ? t("stageFailed") : t("stageNotReached");

  return (
    <Card className={`transition-all duration-500 ${shown ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={`flex h-8 w-8 items-center justify-center rounded-xl text-xs font-extrabold ${state === "not-reached" ? "bg-[var(--surface-muted)] text-[var(--ink-faint)]" : "bg-[var(--accent-soft)] text-[var(--accent)]"}`}>{index + 1}</span>
          <h3 className="font-extrabold">{label}</h3>
        </div>
        <Pill tone={STATE_TONE[state]}>{stateLabel}</Pill>
      </div>
      {state === "not-reached" ? null : state === "failed" ? (
        <p className="rounded-xl bg-[var(--danger-bg)] p-3 text-xs text-[var(--danger)]">{stage.error}</p>
      ) : (
        <StageBody stepKey={stepKey} stage={stage} />
      )}
    </Card>
  );
}

function StageBody({ stepKey, stage }: { stepKey: string; stage: StageResult }) {
  const { t } = useLang();

  if (stepKey === "indexing") {
    const chunks = (stage.sample_chunks as { chunk_id?: string; page_number?: number; text?: string }[]) ?? [];
    return (
      <div className="text-xs text-[var(--ink-soft)]">
        <div className="mb-3 flex flex-wrap gap-4">
          <span><b className="text-[var(--ink)]">{String(stage.total_pages ?? 0)}</b> {t("pages")}</span>
          <span><b className="text-[var(--ink)]">{String(stage.chunk_count ?? 0)}</b> {t("chunks")}</span>
          <span><b className="text-[var(--ink)]">{String(stage.char_count ?? 0)}</b> chars</span>
        </div>
        {chunks.map((c, i) => (
          <div key={i} className="mb-2 rounded-xl bg-[var(--surface-muted)] p-3">
            <p className="font-mono text-[10px] text-[var(--ink-faint)]">{c.chunk_id}</p>
            <p className="mt-1">{c.text}</p>
          </div>
        ))}
      </div>
    );
  }

  if (stepKey === "retrieval") {
    const hits = (stage.hits as { rank?: number; page_number?: number; vector_distance?: number; rerank_score?: number; text?: string }[]) ?? [];
    return (
      <div className="text-xs text-[var(--ink-soft)]">
        <p className="mb-2"><b className="text-[var(--ink)]">{String(stage.hit_count ?? 0)}</b> hits</p>
        {hits.map((h, i) => (
          <div key={i} className="mb-2 rounded-xl bg-[var(--surface-muted)] p-3">
            <p className="text-[10px] text-[var(--ink-faint)]">#{h.rank} · {t("page")} {h.page_number ?? "—"} · {t("vectorDistance")} {h.vector_distance ?? "—"} · {t("rerankScore")} {h.rerank_score ?? "—"}</p>
            <p className="mt-1">{h.text}</p>
          </div>
        ))}
      </div>
    );
  }

  if (stepKey === "generation") {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Pill tone={stage.grounded ? "ok" : "pending"}>{stage.grounded ? t("verificationPassed") : t("insufficientEvidence")}</Pill>
        {typeof stage.evidence_strength === "string" && <Pill tone="accent">{stage.evidence_strength}</Pill>}
        {typeof stage.reason === "string" && stage.reason && <span className="text-[var(--ink-soft)]">{stage.reason}</span>}
      </div>
    );
  }

  // final output
  return (
    <div className="chat-ltr text-sm leading-6 text-[var(--ink)]">
      <p className="whitespace-pre-wrap">{String(stage.final_answer ?? "")}</p>
    </div>
  );
}
