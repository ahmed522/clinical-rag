"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "@/components/Icon";
import { Card, EmptyState, Field, PageHeader, Pill, PrimaryButton, SecondaryButton, TextArea } from "@/components/ui";
import { AuthSessionUnavailableError, authenticatedFetch } from "@/lib/auth-api";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";

interface Citation {
  id?: string | null;
  rank?: number | null;
  document: string;
  publisher?: string | null;
  page?: number | null;
  section?: string | null;
  chunk_id?: string | null;
  excerpt?: string | null;
  source_url?: string | null;
  vector_distance?: number | null;
  rerank_score?: number | null;
}

type Strength = "high" | "medium" | "low" | "insufficient";

interface EvidencePackage {
  recommendation: string;
  recommendation_claims: { claim_id: string; text: string; citation_ids: string[] }[];
  supporting_evidence: { claim_id: string; claim: string; citation_ids: string[] }[];
  evidence_strength: Strength;
  safety_notice: string;
  evidence_checked: string[];
  missing_evidence: string;
  checks: { verifier_passed: boolean };
}

interface DoctorMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  grounded?: boolean | null;
  reason?: string | null;
  citations?: Citation[] | null;
  evidence_strength?: string | null;
  evidence?: EvidencePackage | null;
  created_at?: string;
}

// A grounded answer can need two bounded generation attempts (45 seconds
// each) and an independent evidence-verifier call (15 seconds). Keep the
// browser budget above that server-side maximum so it does not abandon a
// still-running, safe response immediately before it is returned.
const DOCTOR_CHAT_TIMEOUT_MS = 130_000;

interface DoctorSession {
  id: string;
  started_at: string;
  message_count: number;
}

function strengthTone(strength: Strength): "ok" | "blue" | "pending" | "danger" {
  if (strength === "high") return "ok";
  if (strength === "medium") return "blue";
  if (strength === "low") return "pending";
  return "danger";
}

function strengthRailColor(strength: Strength): string {
  if (strength === "high") return "var(--ok)";
  if (strength === "medium") return "var(--blue)";
  if (strength === "low") return "var(--pending)";
  return "var(--danger)";
}

function DoctorEvidenceAnswer({ message }: { message: DoctorMessage }) {
  const { t } = useLang();
  const evidence = message.evidence;
  const citations = message.citations ?? [];

  if (!evidence) {
    return <div className={`max-w-[94%] self-start rounded-2xl rounded-bl-md border px-4 py-3 text-sm leading-6 ${message.grounded === false ? "border-[#f2cfcc] bg-[var(--danger-bg)] text-[var(--danger-ink)]" : "border-[var(--border)] bg-white text-[var(--ink)] shadow-[var(--shadow-sm)]"}`}><span className="whitespace-pre-wrap">{message.content}</span></div>;
  }

  const insufficient = evidence.evidence_strength === "insufficient";
  const label = evidence.evidence_strength === "high" ? t("highEvidence") : evidence.evidence_strength === "medium" ? t("mediumEvidence") : evidence.evidence_strength === "low" ? t("lowEvidence") : t("insufficientEvidence");

  return <article className={`flex w-full shrink-0 overflow-hidden rounded-[22px] border bg-white shadow-[var(--shadow)] ${insufficient ? "border-[#efc5c1]" : "border-[#ddd6ee]"}`}>
    <span aria-hidden="true" className="w-1.5 shrink-0" style={{ background: strengthRailColor(evidence.evidence_strength) }} />
    <div className="min-w-0 flex-1">
      <header className={`flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4 ${insufficient ? "border-[#f2cfcc] bg-[var(--danger-bg)]" : "border-[#ddd6ee] bg-[var(--cura-soft)]"}`}>
        <div><p className="text-xs font-extrabold uppercase tracking-[0.14em] text-[var(--ink-faint)]">{t("evidenceStrength")}</p><Pill tone={strengthTone(evidence.evidence_strength)} className="mt-1">{label}</Pill></div>
        {!insufficient && evidence.checks.verifier_passed && <span className="inline-flex items-center gap-1.5 text-xs font-bold text-[var(--ok)]"><Icon name="check" size={15} />{t("verificationPassed")}</span>}
      </header>
      <div className="space-y-5 p-5">
        <section><h3 className="mb-2 flex items-center gap-2 text-sm font-extrabold"><Icon name="chat" size={15} />{t("recommendation")}</h3><p className="whitespace-pre-wrap text-[15px] leading-7 text-[var(--ink)]">{evidence.recommendation || message.content}</p></section>
        {evidence.supporting_evidence.length > 0 && <section><h3 className="mb-2 text-sm font-extrabold">{t("supportingEvidence")}</h3><ul className="space-y-2">{evidence.supporting_evidence.map((item) => <li key={item.claim_id} className="rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] px-3.5 py-3 text-sm leading-6">{item.claim}<span className="ms-2 whitespace-nowrap font-mono text-xs font-extrabold text-[var(--blue)]">{item.citation_ids.map((id) => `[${id}]`).join(" ")}</span></li>)}</ul></section>}
        {citations.length > 0 && <section><h3 className="mb-2 text-sm font-extrabold">{t("citations")}</h3><div className="grid gap-2 sm:grid-cols-2">{citations.map((citation, index) => <div key={citation.id ?? index} className="rounded-xl border border-[var(--border)] bg-white p-3"><div className="flex items-start gap-2"><span className="rounded-lg bg-[var(--blue-soft)] px-2 py-1 font-mono text-xs font-extrabold text-[var(--blue)]">{citation.id ?? `C${index + 1}`}</span><div className="min-w-0"><p className="truncate text-xs font-extrabold">{citation.document}</p><p className="mt-0.5 text-[11px] text-[var(--ink-soft)]">{citation.section || "—"}{citation.page ? ` · p.${citation.page}` : ""}</p></div></div></div>)}</div></section>}
        {insufficient && <section className="grid gap-3 sm:grid-cols-2">{evidence.evidence_checked.length > 0 && <div className="rounded-xl bg-[var(--surface-muted)] p-3.5"><p className="text-xs font-extrabold">{t("checkedSources")}</p><ul className="mt-2 space-y-1 text-xs text-[var(--ink-soft)]">{evidence.evidence_checked.map((source) => <li key={source}>• {source}</li>)}</ul></div>}<div className="rounded-xl bg-[var(--pending-bg)] p-3.5"><p className="text-xs font-extrabold text-[var(--pending)]">{t("missingEvidence")}</p><p className="mt-2 text-xs leading-5 text-[var(--ink-soft)]">{evidence.missing_evidence}</p></div></section>}
        <section className="rounded-xl border border-[#cfe6df] bg-[#f0faf7] p-3.5"><p className="flex items-center gap-2 text-xs font-extrabold text-[var(--ok)]"><Icon name="shield" size={15} />{t("safetyAndLimits")}</p><p className="mt-1.5 text-xs leading-5 text-[var(--ink-soft)]">{evidence.safety_notice}</p></section>
        {citations.length > 0 && <details className="group rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)]"><summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-xs font-extrabold text-[var(--ink-soft)]"><span className="flex items-center gap-2"><Icon name="eye" size={15} />{t("evidenceAudit")}</span><span className="text-[var(--accent)] group-open:rotate-180">⌄</span></summary><div className="space-y-3 border-t border-[var(--border)] p-4">{citations.map((citation, index) => <div key={`audit-${citation.id ?? index}`} className="rounded-xl border border-[var(--border)] bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-sm font-extrabold">[{citation.id ?? `C${index + 1}`}] {citation.document}</p><p className="mt-1 text-xs text-[var(--ink-soft)]">{citation.publisher || "—"} · {citation.section || "—"}{citation.page ? ` · p.${citation.page}` : ""}</p></div>{citation.source_url && <a href={citation.source_url} target="_blank" rel="noopener noreferrer" className="text-xs font-extrabold text-[var(--blue)] hover:underline">{t("openSource")} ↗</a>}</div>{citation.excerpt && <blockquote className="mt-3 border-s-2 border-[var(--accent)] ps-3 text-xs italic leading-5 text-[var(--ink-soft)]">“{citation.excerpt}”</blockquote>}<div className="mt-3 flex flex-wrap gap-2 font-mono text-[10px] font-bold tabular-nums text-[var(--ink-faint)]">{citation.chunk_id && <span>{t("chunkId")}: {citation.chunk_id}</span>}{citation.vector_distance != null && <span>{t("vectorDistance")}: {citation.vector_distance.toFixed(4)}</span>}{citation.rerank_score != null && <span>{t("rerankScore")}: {citation.rerank_score.toFixed(4)}</span>}</div></div>)}</div></details>}
      </div>
    </div>
  </article>;
}

/**
 * The clinician assistant uses the same verified-document RAG pipeline as
 * patient chat, but persists only the doctor's own questions and answers in
 * dedicated doctor tables. It never exposes patient chat history.
 */
export function AssistantTab() {
  const { t, lang } = useLang();
  const { session } = useAuth();
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DoctorMessage[]>([]);
  const [sessions, setSessions] = useState<DoctorSession[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const createSession = useCallback(async () => {
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/doctor/chat/sessions`, { method: "POST" });
      if (!response.ok) throw new Error(t("error"));
      const data = await response.json() as DoctorSession;
      setSessionId(data.id);
      setMessages([]);
      return data.id;
    } catch (cause) {
      if (cause instanceof AuthSessionUnavailableError) return null;
      setError(cause instanceof Error ? cause.message : t("error"));
      return null;
    }
  }, [t]);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (!cancelled) void createSession();
    }, 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [session, createSession]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/doctor/chat/sessions`);
      if (!response.ok) throw new Error(t("error"));
      setSessions(await response.json() as DoctorSession[]);
    } catch (cause) {
      if (!(cause instanceof AuthSessionUnavailableError)) setError(cause instanceof Error ? cause.message : t("error"));
    } finally {
      setHistoryLoading(false);
    }
  }, [t]);

  async function openHistory() {
    setHistoryOpen((open) => !open);
    if (!historyOpen) await loadHistory();
  }

  async function resumeSession(item: DoctorSession) {
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/doctor/chat/${item.id}`);
      if (!response.ok) throw new Error(t("error"));
      setSessionId(item.id);
      setMessages(await response.json() as DoctorMessage[]);
      setHistoryOpen(false);
      setError("");
    } catch (cause) {
      if (!(cause instanceof AuthSessionUnavailableError)) setError(cause instanceof Error ? cause.message : t("error"));
    }
  }

  async function startNewConversation() {
    setHistoryOpen(false);
    setError("");
    await createSession();
  }

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim() || loading || historyOpen) return;
    setLoading(true); setError("");
    const asked = question.trim();
    setQuestion("");
    const activeSession = sessionId ?? await createSession();
    if (!activeSession) { setLoading(false); return; }
    setMessages((current) => [...current, { id: `local-${Date.now()}`, role: "user", content: asked }]);
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/doctor/chat/${activeSession}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: asked }),
      }, DOCTOR_CHAT_TIMEOUT_MS);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? t("error"));
      }
      const reply = await response.json() as DoctorMessage;
      if (activeSession === sessionId || sessionId === null) setMessages((current) => [...current, reply]);
    } catch (cause) {
      if (!(cause instanceof AuthSessionUnavailableError)) {
        setError(cause instanceof Error ? cause.message : t("error"));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={t("roleDoctor")} title={t("assistant")} description={t("doctorAssistantHint")} />
      <div className="flex items-center justify-end gap-2">
        <SecondaryButton type="button" onClick={() => void openHistory()}><Icon name="clock" size={15} />{t("chatHistory")}</SecondaryButton>
        <SecondaryButton type="button" onClick={() => void startNewConversation()}><Icon name="chat" size={15} />{t("newConversation")}</SecondaryButton>
      </div>

      {historyOpen ? (
        <Card className="min-h-[360px]">
          <h2 className="mb-3 text-sm font-extrabold">{t("chatHistory")}</h2>
          {historyLoading ? <p className="text-sm text-[var(--ink-soft)]">{t("loading")}</p>
            : sessions.length === 0 ? <EmptyState icon="clock" title={t("noSessionsYet")} />
              : <div className="grid gap-2">{sessions.map((item) => <button key={item.id} type="button" onClick={() => void resumeSession(item)} className="flex items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] px-4 py-3 text-start transition hover:border-[var(--accent)]"><span className="text-sm font-bold">{new Date(item.started_at).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US")}</span><span className="text-xs text-[var(--ink-soft)]">{item.message_count}</span></button>)}</div>}
        </Card>
      ) : (
        <div ref={scrollRef} className="surface-card motion-reveal chat-ltr flex min-h-[360px] max-h-[calc(100vh-350px)] flex-col gap-3 overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-sm)]">
          {messages.length === 0 && !loading && <EmptyState icon="chat" title={t("evidenceFirstTitle")} description={t("doctorAssistantHint")} />}
          {messages.map((message) => message.role === "user" ? <div key={message.id} className="max-w-[82%] self-end rounded-2xl rounded-br-md bg-[var(--accent)] px-4 py-3 text-sm leading-6 text-white"><span className="whitespace-pre-wrap">{message.content}</span></div> : <DoctorEvidenceAnswer key={message.id} message={message} />)}
          {loading && <p className="self-start rounded-xl bg-[var(--cura-soft)] px-4 py-3 text-sm font-bold text-[var(--ink-soft)]">{t("assistantThinking")}</p>}
        </div>
      )}

      {error && <p role="alert" className="text-sm font-semibold text-[var(--danger)]">{error}</p>}
      <Card>
        <form onSubmit={ask} className="flex flex-col gap-3">
          <Field label={t("typeMessage")}><TextArea value={question} disabled={historyOpen} onChange={(event) => setQuestion(event.target.value)} placeholder={t("typeMessage")} /></Field>
          <PrimaryButton type="submit" disabled={loading || historyOpen || !question.trim()} className="self-start"><Icon name="send" size={16} />{loading ? t("assistantThinking") : t("send")}</PrimaryButton>
        </form>
      </Card>
    </div>
  );
}
