"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "@/components/Icon";
import { PageHeader, Pill } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";

type Mode = "general" | "triage";
type Strength = "high" | "medium" | "low" | "insufficient";

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

  return <article className={`msg-in flex w-full shrink-0 overflow-hidden rounded-[22px] border bg-white shadow-[var(--shadow)] ${insufficient ? "border-[#efc5c1]" : "border-[var(--border)]"}`}>
    <span aria-hidden="true" className="w-1.5 shrink-0" style={{ background: strengthRailColor(evidence.evidence_strength) }} />
    <div className="min-w-0 flex-1">
      <header className={`flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4 ${insufficient ? "border-[#f2cfcc] bg-[var(--danger-bg)]" : "border-[var(--border)] bg-[var(--surface-subtle)]"}`}>
        <div className="flex items-center gap-2"><span className={`flex h-8 w-8 items-center justify-center rounded-xl ${insufficient ? "bg-white text-[var(--danger)]" : "bg-[var(--accent-soft)] text-[var(--accent)]"}`}><Icon name={insufficient ? "shield" : "activity"} size={17} /></span><div><p className="text-xs font-extrabold uppercase tracking-[0.14em] text-[var(--ink-faint)]">{t("evidenceStrength")}</p><Pill tone={strengthTone(evidence.evidence_strength)} className="mt-1">{strengthLabel}</Pill></div></div>
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
  const { t } = useLang();
  const { session } = useAuth();
  const [mode, setMode] = useState<Mode>("general");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // A ref, not a dependency: the access token rotates on Supabase's silent
  // refresh (~hourly, and on tab refocus). Reading it fresh at call time
  // means that rotation never re-triggers the session-start effect below —
  // which previously wiped the conversation and opened a new backend
  // session on every token refresh.
  const accessTokenRef = useRef(session?.access_token);
  accessTokenRef.current = session?.access_token;
  const hasSession = !!session?.access_token;
  // A live-value ref, checked after each async gap. Comparing against the
  // `sessionId` variable captured in handleSend's own closure would always
  // read as equal to itself — this is what actually detects "the session
  // changed while the request was in flight".
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const startSession = useCallback(async (nextMode: Mode, isCurrent: () => boolean) => {
    const token = accessTokenRef.current;
    if (!token) return;
    try {
      const response = await fetch(`${API_BASE_URL}/chat/sessions`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ mode: nextMode }) });
      if (!response.ok || !isCurrent()) return;
      const data = await response.json();
      if (!isCurrent()) return;
      setSessionId(data.id);
      setMessages([]);
    } catch {
      if (isCurrent()) setSessionId(null);
    }
  }, []);

  useEffect(() => {
    if (!hasSession) return;
    let cancelled = false;
    const timer = window.setTimeout(() => void startSession(mode, () => !cancelled), 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
    // Deliberately excludes accessTokenRef's value — token rotation must
    // not restart the session. Only an actual mode switch should.
  }, [hasSession, mode, startSession]);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages, sending]);
  function handleModeChange(nextMode: Mode) { setMode(nextMode); }

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    const token = accessTokenRef.current;
    if (!input.trim() || !token || !sessionId || sending) return;
    const question = input.trim();
    const activeSessionId = sessionId;
    setInput("");
    setMessages((previous) => [...previous, { id: `local-${Date.now()}`, role: "user", content: question, citations: null }]);
    setSending(true);
    try {
      const response = await fetch(`${API_BASE_URL}/chat/${activeSessionId}/message`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ content: question }) });
      if (!response.ok) throw new Error("request failed");
      const data = await response.json();
      // If the session changed while this request was in flight (mode
      // switch mid-send), its reply belongs to a conversation no longer
      // on screen — drop it instead of appending to the wrong thread.
      if (activeSessionId !== sessionIdRef.current) return;
      setMessages((previous) => [...previous, { ...data.message, grounded: data.grounded, reason: data.reason }]);
    } catch {
      if (activeSessionId !== sessionIdRef.current) return;
      setMessages((previous) => [...previous, { id: `err-${Date.now()}`, role: "assistant", content: t("error"), citations: null, grounded: false }]);
    } finally { setSending(false); }
  }

  const tabs: { key: Mode; label: string }[] = [{ key: "general", label: t("chatModeGeneral") }, { key: "triage", label: t("chatModeTriage") }];

  return <div className="flex flex-col gap-4">
    <PageHeader eyebrow={t("verifiedKnowledge")} title={t("evidenceFirstTitle")} description={t("evidenceFirstHint")} />
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-white p-2 shadow-[var(--shadow-sm)]"><div className="flex gap-1 rounded-xl bg-[var(--surface-muted)] p-1">{tabs.map((tab) => <button key={tab.key} onClick={() => handleModeChange(tab.key)} className={`rounded-lg px-3.5 py-2 text-xs font-extrabold transition ${mode === tab.key ? "bg-white text-[var(--accent)] shadow-sm" : "text-[var(--ink-soft)] hover:text-[var(--ink)]"}`}>{tab.label}</button>)}</div><span className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--danger-bg)] px-3 py-2 text-xs font-extrabold text-[var(--danger-ink)]"><Icon name="shield" size={14} />{t("freeAlways")}</span></div>
    <div className="pulse-line" data-active={sending} aria-hidden="true" />
    <div ref={scrollRef} className="chat-ltr clinical-grid flex min-h-[500px] max-h-[calc(100vh-315px)] flex-col gap-4 overflow-y-auto rounded-[24px] border border-[var(--border)] bg-[var(--surface-subtle)] p-4 sm:p-6">
      {messages.length === 0 && !sending && <div className="flex flex-1 flex-col items-center justify-center px-5 text-center"><span className="flex h-16 w-16 items-center justify-center rounded-2xl border border-[#cbe8e1] bg-white text-[var(--accent)] shadow-[var(--shadow-sm)]"><Icon name="chat" size={28} /></span><h2 className="mt-4 text-xl font-extrabold">{t("chatEmptyTitle")}</h2><p className="mt-2 max-w-md text-sm leading-6 text-[var(--ink-soft)]">{t("chatEmptyHint")}</p></div>}
      {messages.map((message) => message.role === "user" ? <div key={message.id} className="msg-in max-w-[82%] shrink-0 self-end rounded-2xl rounded-br-md bg-[var(--accent)] px-4 py-3 text-sm leading-6 text-white shadow-[0_12px_26px_-18px_var(--accent)]"><span className="whitespace-pre-wrap">{message.content}</span></div> : <EvidenceAnswer key={message.id} message={message} />)}
      {sending && <div className="msg-in shrink-0 self-start rounded-2xl border border-[var(--border)] bg-white px-4 py-3 shadow-[var(--shadow-sm)]"><p className="flex items-center gap-2 text-xs font-bold text-[var(--ink-soft)]"><Icon name="activity" size={15} className="text-[var(--accent)] animate-pulse" />{t("assistantThinking")}</p></div>}
    </div>
    <form onSubmit={handleSend} className="flex items-end gap-2 rounded-2xl border border-[var(--border)] bg-white p-2 shadow-[var(--shadow)] focus-within:border-[var(--accent)]"><textarea rows={1} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={t("typeMessage")} className="min-h-11 flex-1 resize-none bg-transparent px-3 py-3 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--ink-faint)]" /><button type="submit" disabled={sending || !input.trim() || !sessionId} aria-label={t("send")} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[var(--accent)] text-white transition hover:bg-[var(--accent-2)] disabled:opacity-40"><Icon name="send" size={18} /></button></form>
  </div>;
}
