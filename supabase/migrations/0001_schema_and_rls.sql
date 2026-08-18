-- =====================================================================
-- Tabibak — multi-tenant schema and Row Level Security
--
-- PRD sec.9 (schema) and sec.4 (multi-tenancy).
--
-- Tenancy model
-- -------------
-- Every clinic is a tenant. RLS is the PRIMARY isolation mechanism, not a
-- second line of defence behind application filters: a query that forgets
-- its WHERE clause still cannot cross a tenant boundary, because the
-- policy is evaluated by the database rather than by the caller.
--
-- The tenant comes from the caller's JWT — specifically from
-- `app_metadata`, which only the service role can write. It is NEVER read
-- from `user_metadata`, which the user themselves can update: putting
-- clinic_id there would let a patient re-tenant their own account and read
-- another clinic's records.
--
-- Every domain table carries clinic_id, including tables that are one hop
-- from the clinic (medical_records, messages), so each policy can filter
-- on the tenant directly instead of trusting a join to be written right.
--
-- Apply with:
--     supabase db push
-- or paste into the SQL editor of a fresh project.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Claim helpers
--
-- SECURITY DEFINER on current_patient_id() is required, not incidental:
-- policies on appointments/messages/etc. need to look up the caller's
-- patient row, and doing that as the caller would re-enter RLS on
-- `patients` and recurse. search_path is pinned for the same reason it
-- always is on a definer function — so the body cannot be hijacked by a
-- caller-controlled search_path.
-- ---------------------------------------------------------------------

create or replace function public.auth_clinic_id()
returns uuid
language sql
stable
as $$
  select nullif(auth.jwt() -> 'app_metadata' ->> 'clinic_id', '')::uuid;
$$;

create or replace function public.auth_role()
returns text
language sql
stable
as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', '');
$$;

create or replace function public.is_clinic_admin()
returns boolean
language sql
stable
as $$
  select public.auth_role() = 'clinic_admin';
$$;


-- ---------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------

create table if not exists public.clinics (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    specialty   text not null default 'General',
    created_at  timestamptz not null default now()
);

create table if not exists public.patients (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    -- Links this patient to their login. Supabase Auth owns credentials;
    -- this table owns the clinical identity.
    auth_id     uuid unique references auth.users(id) on delete set null,
    name        text not null,
    age         integer check (age is null or (age >= 0 and age <= 130)),
    phone       text,
    created_at  timestamptz not null default now()
);

create table if not exists public.doctors (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    name        text not null,
    specialty   text not null default 'General',
    status      text not null default 'available'
                check (status in ('available', 'off')),
    created_at  timestamptz not null default now()
);

create table if not exists public.documents (
    id           uuid primary key default gen_random_uuid(),
    clinic_id    uuid not null references public.clinics(id) on delete cascade,
    title        text not null,
    publisher    text,
    source_url   text,
    topic        text,
    -- Path inside the `guidelines` storage bucket: {clinic_id}/{id}.pdf
    file_path    text not null,
    -- Guardrail #5. Starts false: a clinic admin must confirm the source is
    -- official before it can ground a patient-facing answer.
    verified     boolean not null default false,
    page_count   integer,
    chunk_count  integer,
    uploaded_at  timestamptz not null default now()
);

create table if not exists public.chunks (
    id            uuid primary key default gen_random_uuid(),
    document_id   uuid not null references public.documents(id) on delete cascade,
    clinic_id     uuid not null references public.clinics(id) on delete cascade,
    content       text not null,
    section_title text,
    page_number   integer,
    -- Join key into the vector store. Deterministic (src/chunk.py:
    -- make_chunk_id), so re-ingesting a document reuses the same ids
    -- instead of orphaning every row here.
    vector_ref    text not null
);

create table if not exists public.appointments (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    patient_id  uuid not null references public.patients(id) on delete cascade,
    doctor_id   uuid not null references public.doctors(id) on delete cascade,
    slot        timestamptz not null,
    status      text not null default 'booked'
                check (status in ('booked', 'cancelled', 'done')),
    created_at  timestamptz not null default now()
);

-- One doctor cannot be in two places at once. Partial on status so that
-- cancelling an appointment releases the slot for someone else, rather
-- than blocking it forever with a dead row.
create unique index if not exists idx_appointments_doctor_slot
    on public.appointments(doctor_id, slot)
    where status = 'booked';

create table if not exists public.medical_records (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    patient_id  uuid not null references public.patients(id) on delete cascade,
    diagnosis   text,
    notes       text,
    created_at  timestamptz not null default now()
);

create table if not exists public.chat_sessions (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    patient_id  uuid not null references public.patients(id) on delete cascade,
    mode        text not null default 'general'
                check (mode in ('general', 'triage', 'consult')),
    started_at  timestamptz not null default now()
);

create table if not exists public.messages (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    session_id  uuid not null references public.chat_sessions(id) on delete cascade,
    role        text not null check (role in ('user', 'assistant')),
    content     text not null,
    -- Resolved {document, page, section} actually used, so an answer stays
    -- auditable after the fact — a clinician can check what was claimed
    -- and where it came from.
    citations   jsonb,
    created_at  timestamptz not null default now()
);

create table if not exists public.subscriptions (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    patient_id  uuid not null references public.patients(id) on delete cascade,
    tier        text not null default 'free' check (tier in ('free', 'premium')),
    status      text not null default 'active',
    renews_at   timestamptz
);

-- Tenant-scoped lookups dominate every query, so clinic_id is indexed
-- everywhere it appears.
create index if not exists idx_patients_clinic        on public.patients(clinic_id);
create index if not exists idx_doctors_clinic         on public.doctors(clinic_id);
create index if not exists idx_documents_clinic       on public.documents(clinic_id);
create index if not exists idx_documents_verified     on public.documents(clinic_id, verified);
create index if not exists idx_chunks_clinic          on public.chunks(clinic_id);
create index if not exists idx_chunks_document        on public.chunks(document_id);
create index if not exists idx_appointments_clinic    on public.appointments(clinic_id);
create index if not exists idx_appointments_patient   on public.appointments(patient_id);
create index if not exists idx_records_patient        on public.medical_records(patient_id);
create index if not exists idx_sessions_patient       on public.chat_sessions(patient_id);
create index if not exists idx_messages_session       on public.messages(session_id);
create index if not exists idx_subscriptions_patient  on public.subscriptions(patient_id);


-- ---------------------------------------------------------------------
-- Patient identity helper
--
-- Defined after `patients` exists. SECURITY DEFINER so policies can call
-- it without re-entering RLS on patients (which would recurse).
-- ---------------------------------------------------------------------

create or replace function public.current_patient_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select id from public.patients where auth_id = auth.uid() limit 1;
$$;


-- ---------------------------------------------------------------------
-- Row Level Security
--
-- Enabled on EVERY table. A table with RLS left off is not "open by
-- default" here, it is a silent hole in the isolation guarantee, so the
-- rule is: no table without a policy, no policy without a tenant filter.
--
-- Two shapes are used:
--   clinic-scoped  — the whole clinic may see the row
--   patient-scoped — the clinic must match AND the row must belong to the
--                    calling patient (admins still see all of their own
--                    clinic's rows)
-- ---------------------------------------------------------------------

alter table public.clinics         enable row level security;
alter table public.patients        enable row level security;
alter table public.doctors         enable row level security;
alter table public.documents       enable row level security;
alter table public.chunks          enable row level security;
alter table public.appointments    enable row level security;
alter table public.medical_records enable row level security;
alter table public.chat_sessions   enable row level security;
alter table public.messages        enable row level security;
alter table public.subscriptions   enable row level security;


-- clinics -------------------------------------------------------------
drop policy if exists clinics_select on public.clinics;
create policy clinics_select on public.clinics
    for select using (id = public.auth_clinic_id());

drop policy if exists clinics_admin_update on public.clinics;
create policy clinics_admin_update on public.clinics
    for update using (id = public.auth_clinic_id() and public.is_clinic_admin())
    with check (id = public.auth_clinic_id() and public.is_clinic_admin());


-- patients ------------------------------------------------------------
-- An admin manages everyone in their clinic; a patient sees only self.
drop policy if exists patients_select on public.patients;
create policy patients_select on public.patients
    for select using (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or auth_id = auth.uid())
    );

drop policy if exists patients_admin_write on public.patients;
create policy patients_admin_write on public.patients
    for all using (clinic_id = public.auth_clinic_id() and public.is_clinic_admin())
    with check (clinic_id = public.auth_clinic_id() and public.is_clinic_admin());


-- doctors -------------------------------------------------------------
-- Readable clinic-wide: patients need the list to book against.
drop policy if exists doctors_select on public.doctors;
create policy doctors_select on public.doctors
    for select using (clinic_id = public.auth_clinic_id());

drop policy if exists doctors_admin_write on public.doctors;
create policy doctors_admin_write on public.doctors
    for all using (clinic_id = public.auth_clinic_id() and public.is_clinic_admin())
    with check (clinic_id = public.auth_clinic_id() and public.is_clinic_admin());


-- documents -----------------------------------------------------------
-- Admins see everything they uploaded, including pending review.
-- Patients see ONLY verified documents — guardrail #5 expressed in the
-- database, so an unverified source cannot even be named in a citation.
drop policy if exists documents_select on public.documents;
create policy documents_select on public.documents
    for select using (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or verified)
    );

drop policy if exists documents_admin_write on public.documents;
create policy documents_admin_write on public.documents
    for all using (clinic_id = public.auth_clinic_id() and public.is_clinic_admin())
    with check (clinic_id = public.auth_clinic_id() and public.is_clinic_admin());


-- chunks --------------------------------------------------------------
-- Same rule as their parent document, so retrieval provenance cannot leak
-- text from a source the patient is not allowed to be answered from.
drop policy if exists chunks_select on public.chunks;
create policy chunks_select on public.chunks
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_clinic_admin()
            or exists (
                select 1 from public.documents d
                where d.id = chunks.document_id and d.verified
            )
        )
    );

drop policy if exists chunks_admin_write on public.chunks;
create policy chunks_admin_write on public.chunks
    for all using (clinic_id = public.auth_clinic_id() and public.is_clinic_admin())
    with check (clinic_id = public.auth_clinic_id() and public.is_clinic_admin());


-- appointments --------------------------------------------------------
drop policy if exists appointments_select on public.appointments;
create policy appointments_select on public.appointments
    for select using (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or patient_id = public.current_patient_id())
    );

-- A patient may book, but only for themselves and only in their own
-- clinic — with check is what stops a forged patient_id in the payload.
drop policy if exists appointments_insert on public.appointments;
create policy appointments_insert on public.appointments
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or patient_id = public.current_patient_id())
    );

drop policy if exists appointments_update on public.appointments;
create policy appointments_update on public.appointments
    for update using (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or patient_id = public.current_patient_id())
    )
    with check (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or patient_id = public.current_patient_id())
    );


-- medical_records -----------------------------------------------------
-- Patients read their own history; only the clinic writes it.
drop policy if exists records_select on public.medical_records;
create policy records_select on public.medical_records
    for select using (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or patient_id = public.current_patient_id())
    );

drop policy if exists records_admin_write on public.medical_records;
create policy records_admin_write on public.medical_records
    for all using (clinic_id = public.auth_clinic_id() and public.is_clinic_admin())
    with check (clinic_id = public.auth_clinic_id() and public.is_clinic_admin());


-- chat_sessions -------------------------------------------------------
-- A conversation belongs to the patient who had it. Admins are excluded
-- from reading it: the clinic controls the SOURCES, not the patient's
-- private questions.
drop policy if exists sessions_select on public.chat_sessions;
create policy sessions_select on public.chat_sessions
    for select using (
        clinic_id = public.auth_clinic_id()
        and patient_id = public.current_patient_id()
    );

drop policy if exists sessions_insert on public.chat_sessions;
create policy sessions_insert on public.chat_sessions
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and patient_id = public.current_patient_id()
    );


-- messages ------------------------------------------------------------
drop policy if exists messages_select on public.messages;
create policy messages_select on public.messages
    for select using (
        clinic_id = public.auth_clinic_id()
        and exists (
            select 1 from public.chat_sessions s
            where s.id = messages.session_id
              and s.patient_id = public.current_patient_id()
        )
    );

drop policy if exists messages_insert on public.messages;
create policy messages_insert on public.messages
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and exists (
            select 1 from public.chat_sessions s
            where s.id = messages.session_id
              and s.patient_id = public.current_patient_id()
        )
    );


-- subscriptions -------------------------------------------------------
-- Read-only to the patient. Note nothing in the retrieval or triage path
-- consults this table at all — safety guidance is never gated on tier
-- (guardrail #2), and the cheapest way to guarantee that is for the
-- answer path to have no reason to look here.
drop policy if exists subscriptions_select on public.subscriptions;
create policy subscriptions_select on public.subscriptions
    for select using (
        clinic_id = public.auth_clinic_id()
        and (public.is_clinic_admin() or patient_id = public.current_patient_id())
    );

drop policy if exists subscriptions_admin_write on public.subscriptions;
create policy subscriptions_admin_write on public.subscriptions
    for all using (clinic_id = public.auth_clinic_id() and public.is_clinic_admin())
    with check (clinic_id = public.auth_clinic_id() and public.is_clinic_admin());


-- ---------------------------------------------------------------------
-- Grants
--
-- RLS decides which ROWS are visible; grants decide whether the role may
-- touch the table at all. Both are needed. `anon` is granted nothing:
-- there is no unauthenticated view of any clinical data.
-- ---------------------------------------------------------------------

grant usage on schema public to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant execute on all functions in schema public to authenticated;


-- ---------------------------------------------------------------------
-- Storage — uploaded guideline PDFs
--
-- Private bucket. Objects are keyed {clinic_id}/{document_id}.pdf, so the
-- first path segment is the tenant and the same clinic_id check applies
-- to files as to rows.
-- ---------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('guidelines', 'guidelines', false)
on conflict (id) do nothing;

drop policy if exists guidelines_read on storage.objects;
create policy guidelines_read on storage.objects
    for select using (
        bucket_id = 'guidelines'
        and (storage.foldername(name))[1] = public.auth_clinic_id()::text
    );

drop policy if exists guidelines_admin_write on storage.objects;
create policy guidelines_admin_write on storage.objects
    for all using (
        bucket_id = 'guidelines'
        and (storage.foldername(name))[1] = public.auth_clinic_id()::text
        and public.is_clinic_admin()
    )
    with check (
        bucket_id = 'guidelines'
        and (storage.foldername(name))[1] = public.auth_clinic_id()::text
        and public.is_clinic_admin()
    );
