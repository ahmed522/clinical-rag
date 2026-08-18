"use client";

import { useEffect, useRef, useState } from "react";

import { PrimaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL } from "@/lib/supabase";

type Mode = "general" | "triage" | "consult";

interface Citation {
  document: string;
  page: number | null;
  section: string | null;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  grounded?: boolean;
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

  const authHeaders = session
    ? { Authorization: `Bearer ${session.access_token}`, "Content-Type": "application/json" }
    : null;

  async function startSession(nextMode: Mode) {
    if (!authHeaders) return;
    const response = await fetch(`${API_BASE_URL}/chat/sessions`, {
      method: "POST",
      headers: authHeaders,
      body: JSON.stringify({ mode: nextMode }),
    });
    if (!response.ok) return;
    const data = await response.json();
    setSessionId(data.id);
    setMessages([]);
  }

  useEffect(() => {
    if (authHeaders) startSession(mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function handleModeChange(nextMode: Mode) {
    setMode(nextMode);
    await startSession(nextMode);
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || !authHeaders || !sessionId || sending) return;

    const question = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { id: `local-${Date.now()}`, role: "user", content: question, citations: null }]);
    setSending(true);

    const response = await fetch(`${API_BASE_URL}/chat/${sessionId}/message`, {
      method: "POST",
      headers: authHeaders,
      body: JSON.stringify({ content: question }),
    });
    setSending(false);

    if (!response.ok) {
      setMessages((prev) => [
        ...prev,
        { id: `err-${Date.now()}`, role: "assistant", content: t("error"), citations: null },
      ]);
      return;
    }

    const data = await response.json();
    setMessages((prev) => [
      ...prev,
      {
        id: data.message.id,
        role: "assistant",
        content: data.message.content,
        citations: data.message.citations,
        grounded: data.grounded,
      },
    ]);
  }

  const modeTabs: { key: Mode; label: string }[] = [
    { key: "general", label: t("chatModeGeneral") },
    { key: "triage", label: t("chatModeTriage") },
    { key: "consult", label: t("chatModeConsult") },
  ];

  return (
    <div className="flex flex-col gap-3 h-[calc(100vh-220px)] min-h-[420px]">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex gap-1">
          {modeTabs.map((m) => (
            <button
              key={m.key}
              onClick={() => handleModeChange(m.key)}
              className={`rounded-full px-3.5 py-1.5 text-xs font-bold transition-colors ${
                mode === m.key
                  ? "bg-[var(--accent)] text-[var(--accent-ink)]"
                  : "bg-[var(--surface-muted)] text-[var(--ink-soft)]"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <span className="rounded-full bg-[var(--accent-soft)] text-[var(--accent)] text-xs font-bold px-3 py-1.5 whitespace-nowrap">
          {t("freeAlways")}
        </span>
      </div>

      <div
        ref={scrollRef}
        className="chat-ltr flex-1 overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 flex flex-col gap-3"
      >
        {messages.map((m) => (
          <div
            key={m.id}
            className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
              m.role === "user"
                ? "self-end bg-[var(--accent)] text-[var(--accent-ink)] rounded-br-sm"
                : m.grounded === false
                ? "self-start bg-[var(--danger-bg)] text-[var(--danger-ink)] rounded-bl-sm"
                : "self-start bg-[var(--surface-muted)] text-[var(--ink)] rounded-bl-sm"
            }`}
          >
            {m.content}
            {m.citations && m.citations.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {m.citations.map((c, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 rounded-full bg-[var(--bg-raised)] border border-[var(--border)] px-2.5 py-1 text-[11px] font-semibold text-[var(--accent)]"
                  >
                    Source: {c.document}
                    {c.page ? ` — p.${c.page}` : ""}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={handleSend} className="flex gap-2">
        <TextInput
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("typeMessage")}
          className="flex-1"
        />
        <PrimaryButton type="submit" disabled={sending || !input.trim()}>
          {sending ? t("sending") : t("send")}
        </PrimaryButton>
      </form>
    </div>
  );
}
