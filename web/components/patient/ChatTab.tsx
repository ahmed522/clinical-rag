"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Icon } from "@/components/Icon";
import { Card, CuraAvatar, EmptyState, PageHeader, Pill, SecondaryButton, Skeleton } from "@/components/ui";
import { authenticatedFetch, AuthSessionUnavailableError } from "@/lib/auth-api";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";
import { AppointmentChatAction } from "./AppointmentChatAction";

type Strength = "high" | "medium" | "low" | "insufficient";

interface SessionSummary {
  id: string;
  mode: string;
  started_at: string;
  message_count: number;
}

interface Citation {
  id?: string | null;
  rank?: number | null;
  document: string;
  publisher?: string | null;
  page: number | null;
  section: string | null;
  chunk_id?: string | null;
  source_url?: string | null;
  excerpt?: string | null;
  vector_distance?: number | null;
  rerank_score?: number | null;
}

interface EvidencePackage {
  recommendation: string;
  recommendation_claims: { claim_id: string; text: string; citation_ids: string[] }[];
  supporting_evidence: { claim_id: string; claim: string; citation_ids: string[] }[];
  evidence_strength: Strength;
  safety_notice: string;
  evidence_checked: string[];
  missing_evidence: string;
  checks: {
    retrieval_passed: boolean;
    exact_excerpts_passed: boolean;
    citation_coverage: number;
    evidence_match_passed: boolean;
    safety_passed: boolean;
    verifier_passed: boolean;
  };
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  grounded?: boolean | null;
  reason?: string | null;
  evidence?: EvidencePackage | null;
}

function strengthTone(strength: Strength): "ok" | "blue" | "pending" | "danger" {
  if (strength === "high") return "ok";
  if (strength === "medium") return "blue";
  if (strength === "low") return "pending";
  return "danger";
}

// The rail is the card's signature: a single color-coded spine, read at a
// glance before any text, that carries the same meaning as the strength
// pill next to it — reinforced, not decorative.
function strengthRailColor(strength: Strength): string {
  if (strength === "high") return "var(--ok)";
  if (strength === "medium") return "var(--blue)";
  if (strength === "low") return "var(--pending)";
  return "var(--danger)";
}

function EvidenceAnswer({ message }: { message: Message }) {
  const { t } = useLang();
  const evidence = message.evidence;
  const citations = message.citations ?? [];

  if (!evidence) {
    // shrink-0: without it, a flex column with a bounded height (the
    // scrollable message list) will compress items below their content
    // height instead of scrolling — the bug this whole file had.
    return <div className={`msg-in max-w-[92%] shrink-0 self-start rounded-2xl rounded-bl-md border px-4 py-3 text-sm leading-6 ${message.grounded === false ? "border-[#f2cfcc] bg-[var(--danger-bg)] text-[var(--danger-ink)]" : "border-[var(--border)] bg-white text-[var(--ink)] shadow-[var(--shadow-sm)]"}`}><span className="whitespace-pre-wrap">{message.content}</span></div>;
  }

  const strengthLabel = evidence.evidence_strength === "high" ? t("highEvidence") : evidence.evidence_strength === "medium" ? t("mediumEvidence") : evidence.evidence_strength === "low" ? t("lowEvidence") : t("insufficientEvidence");
  const insufficient = evidence.evidence_strength === "insufficient";

  return <article className={`msg-in flex w-full shrink-0 overflow-hidden rounded-[22px] border bg-white shadow-[var(--shadow)] ${insufficient ? "border-[#efc5c1]" : "border-[#ddd6ee]"}`}>
    <span aria-hidden="true" className="w-1.5 shrink-0" style={{ background: strengthRailColor(evidence.evidence_strength) }} />
    <div className="min-w-0 flex-1">
      <header className={`flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4 ${insufficient ? "border-[#f2cfcc] bg-[var(--danger-bg)]" : "border-[#ddd6ee] bg-[var(--cura-soft)]"}`}>
        <div className="flex items-center gap-2">{insufficient ? <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-[var(--danger)]"><Icon name="shield" size={17} /></span> : <CuraAvatar size={34} />}<div><p className="text-xs font-extrabold uppercase tracking-[0.14em] text-[var(--ink-faint)]">{t("evidenceStrength")}</p><Pill tone={strengthTone(evidence.evidence_strength)} className="mt-1">{strengthLabel}</Pill></div></div>
        {!insufficient && evidence.checks.verifier_passed && <span className="inline-flex items-center gap-1.5 text-xs font-bold text-[var(--ok)]"><Icon name="check" size={15} />{t("verificationPassed")}</span>}
      </header>

      <div className="space-y-5 p-5">
        <section><h3 className="mb-2 flex items-center gap-2 text-sm font-extrabold"><span className="flex h-6 w-6 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]"><Icon name="chat" size={13} /></span>{t("recommendation")}</h3><p className="whitespace-pre-wrap text-[15px] leading-7 text-[var(--ink)]">{evidence.recommendation || message.content}</p></section>

        {evidence.supporting_evidence.length > 0 && <section><h3 className="mb-2 text-sm font-extrabold">{t("supportingEvidence")}</h3><ul className="space-y-2">{evidence.supporting_evidence.map((item) => <li key={item.claim_id} className="rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] px-3.5 py-3 text-sm leading-6"><span className="me-2 text-[var(--accent)]">●</span>{item.claim}<span className="ms-2 whitespace-nowrap font-mono text-xs font-extrabold text-[var(--blue)]">{item.citation_ids.map((id) => `[${id}]`).join(" ")}</span></li>)}</ul></section>}

        {citations.length > 0 && <section><h3 className="mb-2 text-sm font-extrabold">{t("citations")}</h3><div className="grid gap-2 sm:grid-cols-2">{citations.map((citation, index) => <div key={citation.id ?? index} className="rounded-xl border border-[var(--border)] bg-white p-3"><div className="flex items-start gap-2"><span className="rounded-lg bg-[var(--blue-soft)] px-2 py-1 font-mono text-xs font-extrabold text-[var(--blue)]">{citation.id ?? `C${index + 1}`}</span><div className="min-w-0"><p className="truncate text-xs font-extrabold">{citation.document}</p><p className="mt-0.5 text-[11px] text-[var(--ink-soft)]">{citation.section || "—"}{citation.page ? ` · p.${citation.page}` : ""}</p></div></div></div>)}</div></section>}

        {insufficient && <section className="grid gap-3 sm:grid-cols-2">{evidence.evidence_checked.length > 0 && <div className="rounded-xl bg-[var(--surface-muted)] p-3.5"><p className="text-xs font-extrabold text-[var(--ink)]">{t("checkedSources")}</p><ul className="mt-2 space-y-1 text-xs text-[var(--ink-soft)]">{evidence.evidence_checked.map((source) => <li key={source}>• {source}</li>)}</ul></div>}<div className="rounded-xl bg-[var(--pending-bg)] p-3.5"><p className="text-xs font-extrabold text-[var(--pending)]">{t("missingEvidence")}</p><p className="mt-2 text-xs leading-5 text-[var(--ink-soft)]">{evidence.missing_evidence}</p></div></section>}

        <section className="rounded-xl border border-[#cfe6df] bg-[#f0faf7] p-3.5"><p className="flex items-center gap-2 text-xs font-extrabold text-[var(--ok)]"><Icon name="shield" size={15} />{t("safetyAndLimits")}</p><p className="mt-1.5 text-xs leading-5 text-[var(--ink-soft)]">{evidence.safety_notice}</p></section>

        {citations.length > 0 && <details className="group rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)]"><summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-xs font-extrabold text-[var(--ink-soft)]"><span className="flex items-center gap-2"><Icon name="eye" size={15} />{t("evidenceAudit")}</span><span className="text-[var(--accent)] group-open:rotate-180">⌄</span></summary><div className="space-y-3 border-t border-[var(--border)] p-4">{citations.map((citation, index) => <div key={`audit-${citation.id ?? index}`} className="rounded-xl border border-[var(--border)] bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-sm font-extrabold">[{citation.id ?? `C${index + 1}`}] {citation.document}</p><p className="mt-1 text-xs text-[var(--ink-soft)]">{citation.publisher || "—"} · {citation.section || "—"}{citation.page ? ` · p.${citation.page}` : ""}</p></div>{citation.source_url && <a href={citation.source_url} target="_blank" rel="noopener noreferrer" className="text-xs font-extrabold text-[var(--blue)] hover:underline">{t("openSource")} ↗</a>}</div>{citation.excerpt && <blockquote className="mt-3 border-s-2 border-[var(--accent)] ps-3 text-xs italic leading-5 text-[var(--ink-soft)]">“{citation.excerpt}”</blockquote>}<div className="mt-3 flex flex-wrap gap-2 font-mono text-[10px] font-bold tabular-nums text-[var(--ink-faint)]">{citation.chunk_id && <span>{t("chunkId")}: {citation.chunk_id}</span>}{citation.vector_distance != null && <span>{t("vectorDistance")}: {citation.vector_distance.toFixed(4)}</span>}{citation.rerank_score != null && <span>{t("rerankScore")}: {citation.rerank_score.toFixed(4)}</span>}</div></div>)}</div></details>}
      </div>
    </div>
  </article>;
}

export function ChatTab() {
  const router = useRouter();
  const { t, lang } = useLang();
  const { session } = useAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionError, setSessionError] = useState(false);
  const [appointmentAction, setAppointmentAction] = useState<"book" | "cancel" | "reschedule" | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const hasSession = !!session;
  // A live-value ref, checked after each async gap. Comparing against the
  // `sessionId` variable captured in handleSend's own closure would always
  // read as equal to itself — this is what actually detects "the session
  // changed while the request was in flight".
  const sessionIdRef = useRef(sessionId);

  useEffect(() => { sessionIdRef.current = sessionId; }, [sessionId]);

  const startSession = useCallback(async (isCurrent: () => boolean) => {
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/chat/sessions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "general" }) });
      if (!response.ok || !isCurrent()) return null;
      const data = await response.json();
      if (!isCurrent()) return null;
      // Keep the live ref in sync immediately. React applies setState on the
      // next render, but an on-demand session can send its first message now.
      sessionIdRef.current = data.id;
      setSessionId(data.id);
      setMessages([]);
      setSessionError(false);
      return data.id as string;
    } catch (cause) {
      if (cause instanceof AuthSessionUnavailableError) {
        router.replace("/login");
        return null;
      }
      if (isCurrent()) {
        setSessionId(null);
        setSessionError(true);
      }
      return null;
    }
  }, [router]);

  useEffect(() => {
    if (!hasSession) return;
    let cancelled = false;
    const timer = window.setTimeout(() => void startSession(() => !cancelled), 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [hasSession, startSession]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages, sending]);

  async function loadSessions() {
    setSessionsLoading(true);
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/chat/sessions`);
      if (!response.ok) return;
      setSessions(await response.json());
    } catch (cause) {
      if (cause instanceof AuthSessionUnavailableError) router.replace("/login");
    }
    finally { setSessionsLoading(false); }
  }

  function openHistory() { setHistoryOpen(true); void loadSessions(); }

  async function resumeSession(target: SessionSummary) {
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/chat/${target.id}`);
      if (!response.ok) return;
      const history = await response.json();
      setSessionId(target.id);
      setMessages(history);
      setAppointmentAction(null);
      setHistoryOpen(false);
    } catch (cause) {
      if (cause instanceof AuthSessionUnavailableError) router.replace("/login");
    }
  }

  function startNewFromHistory() {
    setHistoryOpen(false);
    void startSession(() => true);
  }

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    if (!input.trim() || !session || sending || historyOpen) return;
    setSending(true);
    let activeSessionId = sessionId;
    if (!activeSessionId) {
      activeSessionId = await startSession(() => true);
      if (!activeSessionId) {
        setSending(false);
        return;
      }
    }
    const question = input.trim();
    setInput("");
    setMessages((previous) => [...previous, { id: `local-${Date.now()}`, role: "user", content: question, citations: null }]);
    try {
      // RAG generation and independent evidence verification can legitimately
      // take longer than ordinary CRUD requests. Do not abandon an answer
      // that the backend is still safely generating and persisting.
      const response = await authenticatedFetch(`${API_BASE_URL}/chat/${activeSessionId}/message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: question }) }, 90_000);
      if (!response.ok) throw new Error("request failed");
      const data = await response.json();
      // If the session changed while this request was in flight (mode
      // switch mid-send), its reply belongs to a conversation no longer
      // on screen — drop it instead of appending to the wrong thread.
      if (activeSessionId !== sessionIdRef.current) return;
      setMessages((previous) => [...previous, { ...data.message, grounded: data.grounded, reason: data.reason }]);
      setAppointmentAction(data.action ?? null);
    } catch (cause) {
      if (cause instanceof AuthSessionUnavailableError) {
        router.replace("/login");
        return;
      }
      if (activeSessionId !== sessionIdRef.current) return;
      setMessages((previous) => [...previous, { id: `err-${Date.now()}`, role: "assistant", content: t("error"), citations: null, grounded: false }]);
    } finally { setSending(false); }
  }

  return <div className="flex flex-col gap-4">
    <PageHeader eyebrow="Cura" title={t("patientAssistantTitle")} description={t("patientAssistantHint")} />
    <div className="motion-reveal flex justify-end rounded-2xl border border-[#ded7ef] bg-white p-2 shadow-[var(--shadow-sm)]"><button type="button" onClick={() => historyOpen ? setHistoryOpen(false) : openHistory()} aria-label={t("chatHistory")} title={t("chatHistory")} className={`inline-flex h-9 w-9 items-center justify-center rounded-xl border transition ${historyOpen ? "border-[var(--cura)] bg-[var(--cura-soft)] text-[var(--cura-strong)]" : "border-[var(--border)] bg-white text-[var(--ink-soft)] hover:border-[var(--cura)] hover:text-[var(--cura-strong)]"}`}><Icon name="clock" size={16} /></button></div>
    <div className="pulse-line" data-active={sending} aria-hidden="true" />
    {historyOpen ? <div className="flex min-h-[500px] max-h-[calc(100vh-315px)] flex-col gap-3 overflow-y-auto rounded-[24px] border border-[var(--border)] bg-[var(--surface-subtle)] p-4 sm:p-6">
      <div className="flex items-center justify-between gap-3"><h2 className="text-sm font-extrabold">{t("chatHistory")}</h2><SecondaryButton type="button" onClick={startNewFromHistory} className="text-xs"><Icon name="chat" size={15} />{t("newConversation")}</SecondaryButton></div>
      {sessionsLoading ? <div className="grid gap-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
        : sessions.length === 0 ? <EmptyState icon="clock" title={t("noSessionsYet")} />
        : <div className="grid gap-2">{sessions.map((item) => <Card key={item.id} className="cursor-pointer p-4 transition hover:border-[var(--accent)]"><button type="button" onClick={() => void resumeSession(item)} className="flex w-full items-center justify-between gap-3 text-start"><span className="text-xs text-[var(--ink-soft)]">{new Date(item.started_at).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US")}</span><span className="text-xs font-bold text-[var(--ink-faint)]">{item.message_count}</span></button></Card>)}</div>}
    </div> : <div ref={scrollRef} className="chat-ltr clinical-grid flex min-h-[500px] max-h-[calc(100vh-315px)] flex-col gap-4 overflow-y-auto rounded-[24px] border border-[var(--border)] bg-[var(--surface-subtle)] p-4 sm:p-6">
      {messages.length === 0 && !sending && <div className="motion-reveal flex flex-1 flex-col items-center justify-center px-5 text-center"><CuraAvatar size={68} /><p className="mt-3 text-xs font-extrabold uppercase tracking-[0.18em] text-[var(--cura-strong)]">Cura</p><h2 className="mt-2 text-xl font-extrabold">{t("chatEmptyTitle")}</h2><p className="mt-2 max-w-md text-sm leading-6 text-[var(--ink-soft)]">{t("patientAssistantHint")}</p></div>}
      {messages.map((message) => message.role === "user" ? <div key={message.id} className="msg-in max-w-[82%] shrink-0 self-end rounded-2xl rounded-br-md bg-[var(--accent)] px-4 py-3 text-sm leading-6 text-white shadow-[0_12px_26px_-18px_var(--accent)]"><span className="whitespace-pre-wrap">{message.content}</span></div> : <EvidenceAnswer key={message.id} message={message} />)}
      {appointmentAction && sessionId && <AppointmentChatAction action={appointmentAction} sessionId={sessionId} onComplete={(message) => { setMessages((previous) => [...previous, message as Message]); setAppointmentAction(null); }} />}
      {sending && <div className="msg-in shrink-0 self-start rounded-2xl border border-[#ddd6ee] bg-[var(--cura-soft)] px-4 py-3 shadow-[var(--shadow-sm)]"><p className="flex items-center gap-2 text-xs font-bold text-[var(--ink-soft)]"><Icon name="activity" size={15} className="animate-pulse text-[var(--cura-strong)]" />{t("patientAssistantThinking")}</p></div>}
    </div>}
    {sessionError && <div role="alert" className="motion-reveal flex items-center justify-between gap-3 rounded-xl border border-[#f1d9a5] bg-[var(--pending-bg)] px-4 py-3 text-xs font-bold text-[var(--pending)]"><span>{t("connectionError")}</span><button type="button" onClick={() => void startSession(() => true)} className="rounded-lg bg-white px-3 py-1.5 text-[var(--ink)] shadow-sm">{t("retry")}</button></div>}
    <form onSubmit={handleSend} className="motion-reveal flex items-end gap-2 rounded-2xl border border-[var(--border)] bg-white p-2 shadow-[var(--shadow)] transition-all focus-within:border-[var(--cura)] focus-within:ring-4 focus-within:ring-[rgba(142,124,195,.1)]"><textarea rows={1} value={input} disabled={historyOpen} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={t("typeMessage")} className="min-h-11 flex-1 resize-none bg-transparent px-3 py-3 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--ink-faint)] disabled:opacity-50" /><button type="submit" disabled={sending || !input.trim() || historyOpen} aria-label={t("send")} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[var(--cura)] text-white shadow-[0_10px_24px_-14px_rgba(142,124,195,.9)] transition-all hover:-translate-y-0.5 hover:bg-[var(--cura-strong)] disabled:opacity-40"><Icon name="send" size={18} /></button></form>
  </div>;
}
