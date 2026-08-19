-- =====================================================================
-- Tabibak RAG MVP reliability
--
-- A document is not safe to retrieve merely because a row exists. This
-- migration records the ingestion lifecycle, extraction diagnostics, and
-- doctor approval provenance, and makes `ready + verified` the database
-- definition of a patient-visible source.
-- =====================================================================

alter table public.documents
    add column if not exists status text not null default 'ready';

-- Existing documents predate lifecycle tracking and were already fully
-- ingested. New callers explicitly insert `processing`; direct inserts that
-- omit status begin as `uploaded` and cannot be verified accidentally.
alter table public.documents alter column status set default 'uploaded';

alter table public.documents
    add column if not exists processing_error text,
    add column if not exists uploaded_by uuid references auth.users(id) on delete set null,
    add column if not exists verified_by uuid references auth.users(id) on delete set null,
    add column if not exists verified_at timestamptz,
    add column if not exists file_sha256 text,
    add column if not exists extraction_report jsonb not null default '{}'::jsonb,
    add column if not exists extraction_version text,
    add column if not exists chunking_version text;

alter table public.documents
    drop constraint if exists documents_status_check;
alter table public.documents
    add constraint documents_status_check
    check (status in ('uploaded', 'processing', 'ready', 'failed'));

alter table public.documents
    drop constraint if exists documents_verified_requires_ready;
alter table public.documents
    add constraint documents_verified_requires_ready
    check (not verified or status = 'ready');

alter table public.documents
    drop constraint if exists documents_sha256_format;
alter table public.documents
    add constraint documents_sha256_format
    check (file_sha256 is null or file_sha256 ~ '^[0-9a-f]{64}$');

create index if not exists idx_documents_retrievable
    on public.documents(clinic_id, status, verified);
create index if not exists idx_documents_sha256
    on public.documents(clinic_id, file_sha256);

-- Doctors see processing and failed rows for diagnostics. Patients see only
-- sources that completed ingestion and were explicitly doctor-approved.
drop policy if exists documents_select on public.documents;
create policy documents_select on public.documents
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_doctor()
            or (status = 'ready' and verified)
        )
    );

drop policy if exists chunks_select on public.chunks;
create policy chunks_select on public.chunks
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_doctor()
            or exists (
                select 1
                from public.documents d
                where d.id = chunks.document_id
                  and d.status = 'ready'
                  and d.verified
            )
        )
    );

comment on column public.documents.status is
    'RAG ingestion lifecycle: uploaded, processing, ready, or failed.';
comment on column public.documents.extraction_report is
    'Page-level text/OCR quality diagnostics produced before indexing.';
comment on column public.documents.file_sha256 is
    'SHA-256 of the uploaded bytes for provenance and duplicate detection.';
