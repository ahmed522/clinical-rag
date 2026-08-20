"use client";

import { useState } from "react";

import { Icon, type IconName } from "@/components/Icon";
import { Card, Field, MetricCard, PageHeader, Pill, PrimaryButton, TextArea, TextInput } from "@/components/ui";
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
  langsmith_trace_url?: string | null;
}

type StageState = "passed" | "failed" | "not-reached";
type NodeKey = "indexing" | "retrieval" | "generation" | "final";
interface Node { key: NodeKey; label: string; stage: StageResult }

const NODE_ICON: Record<NodeKey, IconName> = {
  indexing: "upload",
  retrieval: "eye",
  generation: "chat",
  final: "check",
};

const STATE_TONE: Record<StageState, "ok" | "danger" | "neutral"> = {
  passed: "ok",
  failed: "danger",
  "not-reached": "neutral",
};

const formatScore = (value: unknown) => (typeof value === "number" ? value.toFixed(4) : "—");

/**
 * The Test section: re-run a doctor's problem document through the real
 * pipeline (indexing -> retrieval -> generation -> final output) inside an
 * isolated, throwaway index, then let IT walk the "signal chain" stage by
 * stage to see exactly where an answer was lost.
 */
export function PipelineTestTab() {
  const { t } = useLang();
  const [documentId, setDocumentId] = useState("");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [selected, setSelected] = useState(0);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    if (!documentId.trim() || !question.trim()) return;
    setLoading(true); setError(""); setResult(null); setSelected(0);
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/it/pipeline-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: documentId.trim(), question: question.trim() }),
      }, 180_000);
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail ?? t("error")); }
      const data = (await response.json()) as PipelineResult;
      setResult(data);
      const order = [data.stages.indexing, data.stages.retrieval, data.stages.generation, data.stages.generation];
      const failedIndex = order.findIndex((s) => s.status === "error");
      setSelected(failedIndex !== -1 ? failedIndex : order.length - 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("error"));
    } finally {
      setLoading(false);
    }
  }

  // "final" reuses the generation stage: it carries the answer text, and
  // inherits generation's pass/fail so a generation error also severs it.
  const nodes: Node[] = result
    ? [
        { key: "indexing", label: t("stageIndexing"), stage: result.stages.indexing },
        { key: "retrieval", label: t("stageRetrieval"), stage: result.stages.retrieval },
        { key: "generation", label: t("stageGeneration"), stage: result.stages.generation },
        { key: "final", label: t("finalOutput"), stage: result.stages.generation },
      ]
    : [];

  // First failed stage severs the chain: everything after it is "not reached".
  const firstFailure = nodes.findIndex((n) => n.stage.status === "error");
  const stateFor = (index: number): StageState => {
    if (firstFailure !== -1 && index > firstFailure) return "not-reached";
    return nodes[index].stage.status === "error" ? "failed" : "passed";
  };

  const verified = result?.document.verified;

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
        <>
          <Verdict result={result} nodes={nodes} firstFailure={firstFailure} />

          {verified === false && (
            <Card className="flex items-start gap-3 border-[#f1d9a5] bg-[var(--pending-bg)]">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#fdeecd] text-[var(--pending)]"><Icon name="help" size={16} /></span>
              <div>
                <h4 className="text-sm font-extrabold text-[var(--pending)]">{t("documentUnverifiedTitle")}</h4>
                <p className="mt-1 text-xs leading-5 text-[var(--ink-soft)]">{t("documentUnverifiedHint")}</p>
              </div>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
            <Card>
              <div className="mb-4 flex items-center justify-between gap-3">
                <h2 className="text-sm font-extrabold">{t("signalChain")}</h2>
                <Pill tone={firstFailure === -1 ? "ok" : "danger"}>
                  {nodes.filter((_, i) => stateFor(i) === "passed").length}/{nodes.length}
                </Pill>
              </div>
              <div className="relative flex flex-col gap-1">
                <span className="pointer-events-none absolute bottom-6 top-6 w-px bg-[var(--border)] start-[23px]" aria-hidden="true" />
                {nodes.map((node, index) => {
                  const state = stateFor(index);
                  return (
                    <button
                      key={node.key}
                      type="button"
                      onClick={() => setSelected(index)}
                      aria-current={selected === index ? "step" : undefined}
                      className={`relative z-10 flex items-start gap-3 rounded-xl p-2 text-start transition-all ${selected === index ? "bg-[var(--accent-soft)]" : "hover:bg-[var(--surface-muted)]"}`}
                    >
                      <span
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition-all ${
                          state === "passed"
                            ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                            : state === "failed"
                              ? "border-[var(--danger)] bg-[var(--danger)] text-white"
                              : "border-dashed border-[var(--border)] bg-[var(--surface-muted)] text-[var(--ink-faint)] opacity-60"
                        }`}
                      >
                        <Icon name={NODE_ICON[node.key]} size={16} />
                      </span>
                      <span className="min-w-0 flex-1 pt-1">
                        <span className="block text-sm font-extrabold">{node.label}</span>
                        <span className="mt-0.5 block truncate text-[11px] text-[var(--ink-faint)]">{nodeMeta(node, state, t)}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </Card>

            <Card className="min-h-[22rem]">
              {nodes[selected] && <StageInspector node={nodes[selected]} state={stateFor(selected)} />}
            </Card>
          </div>

          <Card className={`flex flex-wrap items-center gap-3 ${result.langsmith_trace_url ? "" : "border-dashed"}`}>
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${result.langsmith_trace_url ? "bg-[var(--ok-bg)] text-[var(--ok)]" : "bg-[var(--blue-soft)] text-[var(--blue)]"}`}>
              <Icon name="clock" size={18} />
            </span>
            <div className="flex-1">
              <h3 className="text-sm font-extrabold">{t("langsmithTraceTitle")}</h3>
              <p className="mt-0.5 text-xs text-[var(--ink-soft)]">{result.langsmith_trace_url ? t("langsmithConfiguredHint") : t("langsmithNotConfigured")}</p>
            </div>
            {result.langsmith_trace_url ? (
              <a
                href={result.langsmith_trace_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-[var(--radius-sm)] border border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-2 text-xs font-bold text-[var(--accent-2)] transition-all hover:-translate-y-0.5"
              >
                {t("langsmithLink")} ↗
              </a>
            ) : (
              <span className="cursor-not-allowed rounded-[var(--radius-sm)] border border-[var(--border)] px-3 py-2 text-xs font-bold text-[var(--ink-faint)]">
                {t("langsmithLink")} ↗
              </span>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function nodeMeta(node: Node, state: StageState, t: ReturnType<typeof useLang>["t"]): string {
  if (state === "not-reached") return t("stageNotReached");
  if (state === "failed") return t("stageFailed");
  const stage = node.stage;
  switch (node.key) {
    case "indexing":
      return `${String(stage.chunk_count ?? 0)} ${t("chunks")} · ${String(stage.total_pages ?? 0)} ${t("pages")}`;
    case "retrieval":
      return `${String(stage.hit_count ?? 0)} ${t("hits")}`;
    case "generation":
      return stage.grounded ? t("verificationPassed") : t("insufficientEvidence");
    case "final": {
      const citations = (stage.citations as unknown[] | undefined)?.length ?? 0;
      return `${citations} ${t("citations")}`;
    }
  }
}

function Verdict({ result, nodes, firstFailure }: { result: PipelineResult; nodes: Node[]; firstFailure: number }) {
  const { t } = useLang();
  const generation = result.stages.generation;

  let tone: "ok" | "danger" = "ok";
  let icon: IconName = "check";
  let title = t("verdictHealthyTitle");
  let text = t("verdictHealthyText");

  if (firstFailure !== -1) {
    tone = "danger"; icon = "close";
    title = t("verdictFailedTitle");
    text = `${nodes[firstFailure].label} — ${nodes[firstFailure].stage.error ?? t("error")}`;
  } else if (generation.status === "ok" && generation.grounded === false) {
    tone = "danger"; icon = "close";
    title = t("verdictUngroundedTitle");
    text = typeof generation.reason === "string" && generation.reason ? generation.reason : t("verdictUngroundedText");
  } else if (generation.status === "ok") {
    const citations = (generation.citations as unknown[] | undefined)?.length ?? 0;
    text = `${t("verdictHealthyText")} ${citations} ${t("citations")}.`;
  }

  return (
    <Card className={`flex items-start gap-3 ${tone === "ok" ? "border-[#c8e9da] bg-[#f4fbf8]" : "border-[#f2cfcc] bg-[var(--danger-bg)]"}`}>
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tone === "ok" ? "bg-[var(--ok-bg)] text-[var(--ok)]" : "bg-[#fbdedb] text-[var(--danger)]"}`}>
        <Icon name={icon} size={19} strokeWidth={2.6} />
      </span>
      <div>
        <h2 className={`text-base font-extrabold ${tone === "ok" ? "text-[var(--ok)]" : "text-[var(--danger-ink)]"}`}>{title}</h2>
        <p className="mt-1 max-w-[70ch] text-sm leading-5 text-[var(--ink-soft)]">{text}</p>
      </div>
    </Card>
  );
}

function StageInspector({ node, state }: { node: Node; state: StageState }) {
  const { t } = useLang();
  const stateLabel = state === "passed" ? t("stagePassed") : state === "failed" ? t("stageFailed") : t("stageNotReached");

  return (
    <div>
      <div className="mb-4 flex items-start justify-between gap-3">
        <h2 className="text-lg font-extrabold">{node.label}</h2>
        <Pill tone={STATE_TONE[state]}>{stateLabel}</Pill>
      </div>
      {state === "not-reached" ? (
        <p className="text-sm text-[var(--ink-soft)]">{t("stageNotReachedHint")}</p>
      ) : state === "failed" ? (
        <p className="rounded-xl bg-[var(--danger-bg)] p-3 text-xs text-[var(--danger)]">{node.stage.error}</p>
      ) : (
        <StageBody node={node} />
      )}
    </div>
  );
}

function StageBody({ node }: { node: Node }) {
  const { t } = useLang();
  const stage = node.stage;

  if (node.key === "indexing") {
    const chunks = (stage.sample_chunks as { chunk_id?: string; page_number?: number; text?: string }[] | undefined) ?? [];
    const warnings = (stage.warnings as string[] | undefined) ?? [];
    return (
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard label={t("pages")} value={String(stage.total_pages ?? 0)} />
          <MetricCard label={t("chunks")} value={String(stage.chunk_count ?? 0)} tone="blue" />
          <MetricCard label={t("vectors")} value={String(stage.vector_count ?? 0)} tone="ok" />
          <MetricCard label={t("charCount")} value={String(stage.char_count ?? 0)} />
        </div>
        {warnings.length > 0 && (
          <div className="rounded-xl border border-[#f1d9a5] bg-[var(--pending-bg)] p-3 text-xs text-[var(--pending)]">{warnings.join(" · ")}</div>
        )}
        {chunks.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-extrabold uppercase tracking-[0.08em] text-[var(--ink-faint)]">{t("sampleChunks")}</p>
            <div className="flex flex-col gap-2">
              {chunks.map((c, i) => (
                <div key={i} className="rounded-xl bg-[var(--surface-muted)] p-3">
                  <p className="font-mono text-[10px] text-[var(--ink-faint)]">{c.chunk_id} · {t("page")} {c.page_number ?? "—"}</p>
                  <p className="mt-1 text-xs leading-5 text-[var(--ink)]">{c.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  if (node.key === "retrieval") {
    const hits = (stage.hits as { rank?: number; chunk_id?: string; page_number?: number; vector_distance?: number; rerank_score?: number; text?: string }[] | undefined) ?? [];
    return (
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard label={t("hits")} value={String(stage.hit_count ?? 0)} tone="blue" />
        </div>
        <div>
          <p className="mb-2 text-xs font-extrabold uppercase tracking-[0.08em] text-[var(--ink-faint)]">{t("retrievedChunks")}</p>
          <div className="flex flex-col gap-2">
            {hits.map((h, i) => (
              <div key={i} className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--blue-soft)] text-xs font-extrabold text-[var(--blue)]">{h.rank}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-[11px] font-semibold text-[var(--ink)]">{h.chunk_id}</p>
                  <p className="mt-0.5 truncate text-[11px] text-[var(--ink-faint)]">{t("page")} {h.page_number ?? "—"}</p>
                </div>
                <div className="flex shrink-0 gap-3 text-end">
                  <div><p className="text-xs font-extrabold tabular-nums">{formatScore(h.vector_distance)}</p><p className="text-[10px] font-bold text-[var(--ink-faint)]">{t("vectorDistance")}</p></div>
                  <div><p className="text-xs font-extrabold tabular-nums">{formatScore(h.rerank_score)}</p><p className="text-[10px] font-bold text-[var(--ink-faint)]">{t("rerankScore")}</p></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (node.key === "generation") {
    const citations = (stage.citations as unknown[] | undefined) ?? [];
    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={stage.grounded ? "ok" : "pending"}>{stage.grounded ? t("verificationPassed") : t("insufficientEvidence")}</Pill>
          {typeof stage.evidence_strength === "string" && <Pill tone="accent">{stage.evidence_strength}</Pill>}
          <Pill tone="blue">{citations.length} {t("citations")}</Pill>
        </div>
        {typeof stage.reason === "string" && stage.reason && <p className="text-xs leading-5 text-[var(--ink-soft)]">{stage.reason}</p>}
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
