-- Receptionist scope, internal IT operations, and role-safe RLS.
-- Additive/idempotent schema changes; existing JWT role values remain valid.

-- ---------------------------------------------------------------------
-- Role helper must exist before any policy references it.
-- ---------------------------------------------------------------------
create or replace function public.is_it()
returns boolean
language sql
stable
as $$
  select public.auth_role() = 'it';
$$;

revoke all on function public.is_it() from public, anon;
grant execute on function public.is_it() to authenticated;

-- ---------------------------------------------------------------------
-- Receptionist and clinic contact details.
-- ---------------------------------------------------------------------
alter table public.clinics add column if not exists owner_name text;
alter table public.clinics add column if not exists owner_phone text;
alter table public.clinics add column if not exists owner_email text;

drop policy if exists patients_doctor_insert on public.patients;
drop policy if exists patients_admin_insert on public.patients;
create policy patients_admin_insert on public.patients
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and public.is_clinic_admin()
        and exists (
            select 1
            from public.doctors d
            where d.id = patients.doctor_id
              and d.clinic_id = public.auth_clinic_id()
        )
    );

-- Receptionists must not inherit the patient read branch merely because a
-- source is verified. Doctors see all clinic documents; patients see only
-- verified, ready sources. IT has no direct table access: cross-clinic reads
-- go through require_it backend endpoints and the service client, where an
-- audit write is mandatory.
drop policy if exists documents_select on public.documents;
create policy documents_select on public.documents
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_doctor()
            or (
                public.auth_role() = 'patient'
                and status = 'ready'
                and verified
            )
        )
    );

drop policy if exists chunks_select on public.chunks;
create policy chunks_select on public.chunks
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_doctor()
            or (
                public.auth_role() = 'patient'
                and exists (
                    select 1
                    from public.documents d
                    where d.id = chunks.document_id
                      and d.clinic_id = public.auth_clinic_id()
                      and d.status = 'ready'
                      and d.verified
                )
            )
        )
    );

-- The Storage policy must match the row policy. Without the explicit patient
-- role check, a receptionist could download a verified PDF directly.
drop policy if exists guidelines_read on storage.objects;
create policy guidelines_read on storage.objects
    for select using (
        bucket_id = 'guidelines'
        and (storage.foldername(name))[1] = public.auth_clinic_id()::text
        and (
            public.is_doctor()
            or (
                public.auth_role() = 'patient'
                and exists (
                    select 1
                    from public.documents d
                    where d.clinic_id = public.auth_clinic_id()
                      and d.status = 'ready'
                      and d.verified
                      and name = d.clinic_id::text || '/' || d.id::text || '.pdf'
                )
            )
        )
    );

-- Remove the permissive IT Storage policy if an earlier partial run created
-- it. Raw PDFs are downloaded only inside the require_it backend route.
drop policy if exists guidelines_it_read on storage.objects;

-- ---------------------------------------------------------------------
-- Internal IT identity and operational tables.
-- ---------------------------------------------------------------------
insert into public.clinics (id, name, specialty, slug)
values ('00000000-0000-0000-0000-000000000000', '__internal__', 'Internal', '__internal__')
on conflict (id) do nothing;

create table if not exists public.bug_reports (
    id uuid primary key default gen_random_uuid(),
    clinic_id uuid not null references public.clinics(id) on delete cascade,
    document_id uuid not null references public.documents(id) on delete cascade,
    reported_by uuid not null default auth.uid(),
    issue text not null check (length(btrim(issue)) > 0),
    status text not null default 'open'
        check (status in ('open', 'investigating', 'resolved')),
    created_at timestamptz not null default now(),
    resolved_at timestamptz,
    constraint bug_reports_resolution_consistency check (
        (status = 'resolved' and resolved_at is not null)
        or (status <> 'resolved' and resolved_at is null)
    )
);
create index if not exists idx_bug_reports_status
    on public.bug_reports(status, created_at);
alter table public.bug_reports enable row level security;

drop policy if exists bug_reports_doctor_insert on public.bug_reports;
create policy bug_reports_doctor_insert on public.bug_reports
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and reported_by = auth.uid()
        and exists (
            select 1
            from public.documents d
            where d.id = bug_reports.document_id
              and d.clinic_id = public.auth_clinic_id()
        )
    );

drop policy if exists bug_reports_doctor_select on public.bug_reports;
create policy bug_reports_doctor_select on public.bug_reports
    for select using (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
    );

-- IT reads and updates reports only through the require_it API. Remove any
-- direct policies left by a partial/older version of this migration.
drop policy if exists bug_reports_it_select on public.bug_reports;
drop policy if exists bug_reports_it_update on public.bug_reports;

create table if not exists public.it_access_log (
    id uuid primary key default gen_random_uuid(),
    it_user_id uuid not null,
    action text not null check (length(btrim(action)) > 0),
    target_clinic_id uuid,
    target_document_id uuid,
    detail jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_it_access_log_created
    on public.it_access_log(created_at desc);
alter table public.it_access_log enable row level security;

-- IT can inspect only its own immutable trail. Inserts are performed by the
-- backend service client after require_it and are mandatory/fail-closed.
drop policy if exists it_access_log_it_insert on public.it_access_log;
drop policy if exists it_access_log_it_select on public.it_access_log;
create policy it_access_log_it_select on public.it_access_log
    for select using (
        public.is_it()
        and it_user_id = auth.uid()
    );

-- Aggregate statistics are the only cross-clinic database access exposed
-- directly to an IT JWT. The SECURITY DEFINER function validates the role
-- and writes its audit row inside the same transaction before returning.
create or replace function public.it_clinic_stats()
returns table (
    clinic_id uuid,
    clinic_name text,
    doctor_count bigint,
    patient_count bigint,
    document_count bigint
)
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
begin
    if not public.is_it() then
        raise exception 'IT role required' using errcode = '42501';
    end if;

    insert into public.it_access_log (it_user_id, action)
    values (auth.uid(), 'view_stats');

    return query
    select
        c.id,
        c.name,
        (select count(*) from public.doctors d where d.clinic_id = c.id),
        (select count(*) from public.patients p where p.clinic_id = c.id),
        (select count(*) from public.documents dc where dc.clinic_id = c.id)
    from public.clinics c
    where c.id <> '00000000-0000-0000-0000-000000000000';
end;
$$;

revoke all on function public.it_clinic_stats() from public, anon;
grant execute on function public.it_clinic_stats() to authenticated;

-- Narrow grants for the new tables. RLS remains the row boundary, while
-- column/table grants prevent direct IT mutation of bug reports or audit logs.
revoke all on table public.bug_reports from anon, authenticated;
grant select, insert on table public.bug_reports to authenticated;
grant all on table public.bug_reports to service_role;

revoke all on table public.it_access_log from anon, authenticated;
grant select on table public.it_access_log to authenticated;
grant all on table public.it_access_log to service_role;
