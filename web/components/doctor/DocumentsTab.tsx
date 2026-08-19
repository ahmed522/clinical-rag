"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "@/components/Icon";
import { Card, EmptyState, ErrorText, Field, PageHeader, Pill, PrimaryButton, SecondaryButton, Skeleton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";

interface DocumentRow {
  id: string;
  title: string;
  publisher: string | null;
  source_url: string | null;
  topic: string | null;
  verified: boolean;
  verified_at: string | null;
  verified_by: string | null;
  status: "uploaded" | "processing" | "ready" | "failed";
  processing_error: string | null;
  extraction_report: { warnings?: string[]; text_pages?: number; total_pages?: number } | null;
  page_count: number | null;
  chunk_count: number | null;
  uploaded_at: string;
}

export function DocumentsTab() {
  const { t, lang } = useLang();
  const { session } = useAuth();
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [publisher, setPublisher] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [topic, setTopic] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const { data } = await supabase.from("documents").select("*").order("uploaded_at", { ascending: false });
    setDocs((data as DocumentRow[]) ?? []);
    setLoading(false);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function handleUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!file || !session) return;
    setError(""); setUploading(true);
    const form = new FormData();
    form.append("file", file); form.append("title", title); form.append("publisher", publisher);
    if (sourceUrl) form.append("source_url", sourceUrl);
    if (topic) form.append("topic", topic);
    try {
      const response = await fetch(`${API_BASE_URL}/documents/upload`, { method: "POST", headers: { Authorization: `Bearer ${session.access_token}` }, body: form });
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail ?? t("error")); }
      setTitle(""); setPublisher(""); setSourceUrl(""); setTopic(""); setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setUploadOpen(false); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : t("error")); }
    finally { setUploading(false); }
  }

  async function verify(doc: DocumentRow) {
    if (!session || doc.status !== "ready" || doc.verified) return;
    setError("");
    const response = await fetch(`${API_BASE_URL}/documents/${doc.id}/verify?verified=true`, { method: "PATCH", headers: { Authorization: `Bearer ${session.access_token}` } });
    if (!response.ok) { const body = await response.json().catch(() => null); setError(body?.detail ?? t("error")); return; }
    const updated = await response.json() as DocumentRow;
    setDocs((previous) => previous.map((item) => item.id === doc.id ? updated : item));
  }

  function status(doc: DocumentRow) {
    if (doc.status === "failed") return { label: t("documentFailed"), tone: "danger" as const };
    if (doc.verified) return { label: t("verified"), tone: "ok" as const };
    if (doc.status === "ready") return { label: t("readyForReview"), tone: "accent" as const };
    return { label: doc.status === "processing" ? t("processingDocument") : t("documentUploaded"), tone: "pending" as const };
  }

  return <div>
    <PageHeader eyebrow={t("trustReview")} title={t("trustedLibrary")} description={t("trustedLibraryHint")} action={<PrimaryButton onClick={() => setUploadOpen((value) => !value)}><Icon name={uploadOpen ? "close" : "upload"} size={17} />{uploadOpen ? t("cancelAction") : t("uploadDocument")}</PrimaryButton>} />
    <ErrorText>{error}</ErrorText>

    {uploadOpen && <Card className="mb-6 border-[#bde4dc] bg-[#fbfffe]"><div className="mb-5 flex items-start gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]"><Icon name="shield" size={19} /></span><div><h2 className="font-extrabold">{t("uploadDocument")}</h2><p className="mt-1 text-xs leading-5 text-[var(--ink-soft)]">{t("trustedLibraryHint")}</p></div></div><form onSubmit={handleUpload} className="grid gap-4 sm:grid-cols-2"><Field label={t("documentTitle")}><TextInput required value={title} onChange={(event) => setTitle(event.target.value)} /></Field><Field label={t("publisher")}><TextInput required value={publisher} onChange={(event) => setPublisher(event.target.value)} /></Field><Field label={t("sourceUrl")}><TextInput type="url" placeholder="https://" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /></Field><Field label={t("topic")}><TextInput value={topic} onChange={(event) => setTopic(event.target.value)} /></Field><Field label="PDF"><input ref={fileInputRef} type="file" accept="application/pdf" required onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="block w-full rounded-xl border border-dashed border-[var(--border-strong)] bg-white p-3 text-sm file:me-3 file:rounded-lg file:border-0 file:bg-[var(--accent-soft)] file:px-3 file:py-2 file:font-bold file:text-[var(--accent)]" /></Field><div className="flex items-end"><PrimaryButton type="submit" disabled={uploading || !file} className="w-full sm:w-auto">{uploading ? t("uploading") : t("upload")}</PrimaryButton></div></form></Card>}

    {loading ? <div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-56" /><Skeleton className="h-56" /></div> : docs.length === 0 ? <EmptyState icon="file" title={t("noDocumentsYet")} description={t("trustedLibraryHint")} action={<PrimaryButton onClick={() => setUploadOpen(true)}>{t("uploadDocument")}</PrimaryButton>} /> : <div className="grid gap-4 lg:grid-cols-2">{docs.map((doc) => { const current = status(doc); const report = doc.extraction_report ?? {}; return <Card key={doc.id} className="flex flex-col gap-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="mb-2 flex items-center gap-2"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--blue-soft)] text-[var(--blue)]"><Icon name="file" size={17} /></span><div className="min-w-0"><h2 className="truncate text-sm font-extrabold">{doc.title}</h2><p className="truncate text-xs text-[var(--ink-soft)]">{doc.publisher || "—"}</p></div></div></div><Pill tone={current.tone}>{current.label}</Pill></div>
      <div className="grid grid-cols-2 gap-2"><div className="rounded-xl bg-[var(--surface-muted)] p-3 text-center"><p className="text-lg font-extrabold text-[var(--accent)]">{doc.page_count ?? 0}</p><p className="text-[10px] font-bold text-[var(--ink-faint)]">{t("pages")}</p></div><div className="rounded-xl bg-[var(--surface-muted)] p-3 text-center"><p className="text-lg font-extrabold text-[var(--blue)]">{doc.chunk_count ?? 0}</p><p className="text-[10px] font-bold text-[var(--ink-faint)]">{t("chunks")}</p></div></div>
      <div className="space-y-2 text-xs text-[var(--ink-soft)]"><p><span className="font-extrabold text-[var(--ink)]">{t("topic")}:</span> {doc.topic || "—"}</p><p><span className="font-extrabold text-[var(--ink)]">{t("extractionQuality")}:</span> {report.warnings?.length ? report.warnings.join(" · ") : "Passed"}</p>{doc.source_url && <a href={doc.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex font-bold text-[var(--blue)] hover:underline">{t("openSource")} ↗</a>}</div>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-4"><p className="text-[11px] leading-5 text-[var(--ink-faint)]">{doc.status === "failed" ? doc.processing_error ?? t("documentProcessingFailed") : doc.verified ? `${t("verifiedByDoctor")}${doc.verified_at ? ` · ${new Date(doc.verified_at).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US")}` : ""}` : doc.status === "ready" ? t("excludedUntilVerified") : t("excludedUntilReady")}</p>{doc.status === "ready" && !doc.verified && <SecondaryButton onClick={() => verify(doc)} className="text-xs"><Icon name="check" size={15} />{t("markVerified")}</SecondaryButton>}</div>
    </Card>; })}</div>}
  </div>;
}
