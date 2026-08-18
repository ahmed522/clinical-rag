"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Card, ErrorText, Field, Pill, PrimaryButton, SecondaryButton, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n";
import { API_BASE_URL, supabase } from "@/lib/supabase";

interface DocumentRow {
  id: string;
  title: string;
  publisher: string | null;
  verified: boolean;
  page_count: number | null;
  chunk_count: number | null;
  uploaded_at: string;
}

export function DocumentsTab() {
  const { t } = useLang();
  const { session } = useAuth();
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [publisher, setPublisher] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    // No .eq("clinic_id", ...) here: RLS's documents_select policy already
    // restricts this to the admin's own clinic. See app/routers/documents.py
    // for the same comment on the backend's equivalent query.
    const { data, error: fetchError } = await supabase
      .from("documents")
      .select("*")
      .order("uploaded_at", { ascending: false });
    if (!fetchError && data) setDocs(data as DocumentRow[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !session) return;
    setError("");
    setUploading(true);

    // The one write in this app that cannot go direct to Supabase: only
    // the FastAPI service runs the extraction/chunk/embed pipeline and
    // writes the local Chroma vectors that ground patient answers.
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    if (publisher) form.append("publisher", publisher);

    const response = await fetch(`${API_BASE_URL}/documents/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session.access_token}` },
      body: form,
    });

    setUploading(false);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      setError(body?.detail ?? t("error"));
      return;
    }

    setTitle("");
    setPublisher("");
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setUploadOpen(false);
    load();
  }

  async function toggleVerified(doc: DocumentRow) {
    // Direct write, not a backend call: verifying a document is a plain
    // UPDATE the documents_admin_write RLS policy already permits for a
    // clinic admin on their own clinic's rows.
    const { error: updateError } = await supabase
      .from("documents")
      .update({ verified: !doc.verified })
      .eq("id", doc.id);
    if (!updateError) {
      setDocs((prev) => prev.map((d) => (d.id === doc.id ? { ...d, verified: !d.verified } : d)));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {!uploadOpen ? (
        <PrimaryButton onClick={() => setUploadOpen(true)} className="self-start">
          {t("uploadDocument")}
        </PrimaryButton>
      ) : (
        <Card>
          <form onSubmit={handleUpload} className="flex flex-col gap-3">
            <Field label={t("documentTitle")}>
              <TextInput required value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label={t("publisher")}>
              <TextInput value={publisher} onChange={(e) => setPublisher(e.target.value)} />
            </Field>
            <Field label="PDF">
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf"
                required
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="text-sm"
              />
            </Field>
            <ErrorText>{error}</ErrorText>
            <div className="flex gap-2">
              <PrimaryButton type="submit" disabled={uploading}>
                {uploading ? t("uploading") : t("upload")}
              </PrimaryButton>
              <SecondaryButton type="button" onClick={() => setUploadOpen(false)} disabled={uploading}>
                {t("cancelAction")}
              </SecondaryButton>
            </div>
          </form>
        </Card>
      )}

      {loading ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("loading")}</p>
      ) : docs.length === 0 ? (
        <p className="text-[var(--ink-soft)] text-sm">{t("noDocumentsYet")}</p>
      ) : (
        <div className="flex flex-col gap-3">
          {docs.map((doc) => (
            <Card key={doc.id} className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-bold">{doc.title}</p>
                  <p className="text-xs text-[var(--ink-soft)] mt-0.5">
                    {doc.publisher ? `${doc.publisher} — ` : ""}
                    {doc.page_count ?? 0} {t("pages")} · {doc.chunk_count ?? 0} {t("chunks")}
                  </p>
                </div>
                <Pill tone={doc.verified ? "ok" : "pending"}>
                  {doc.verified ? t("verified") : t("pendingReview")}
                </Pill>
              </div>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <span className="text-xs text-[var(--ink-faint)]">
                  {doc.verified ? t("usedInPatientAnswers") : t("excludedUntilVerified")}
                </span>
                {!doc.verified && (
                  <SecondaryButton onClick={() => toggleVerified(doc)} className="text-xs px-3 py-1.5">
                    {t("markVerified")}
                  </SecondaryButton>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
