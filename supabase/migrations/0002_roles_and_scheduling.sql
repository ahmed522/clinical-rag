-- =====================================================================
-- Tabibak — three-role model (clinic admin / doctor / patient),
-- doctor-owned patients, weekly availability, forced password change,
-- and per-clinic patient entry.
--
-- Builds on 0001_schema_and_rls.sql, already applied. This file only
-- ALTERs existing tables and ADDs new ones/policies — nothing here drops
-- data.
--
-- Role split
-- ----------
-- clinic_admin — administrative only: registers the clinic, adds/manages
--   doctor accounts, views analytics. No access to documents, patients
--   (write), or medical_records at all (read of patients is kept for
--   analytics only — see below).
-- doctor       — the medical actor: uploads/verifies RAG documents,
--   registers and owns patients (patients.doctor_id), views appointments
--   booked with them, views/adds medical history for THEIR patients only,
--   sets weekly availability.
-- patient      — unchanged role, now also self-updates its own row (to
--   clear must_change_password / onboarding_completed and edit its own
--   basic info).
-- =====================================================================


-- ---------------------------------------------------------------------
-- Claim helpers
-- ---------------------------------------------------------------------

create or replace function public.is_doctor()
returns boolean
language sql
stable
as $$
  select public.auth_role() = 'doctor';
$$;


-- ---------------------------------------------------------------------
-- Schema changes
-- ---------------------------------------------------------------------

-- Patient entry point is /clinic/{slug} — resolved via a narrow public
-- backend lookup (app/routers/clinics.py), not a direct anon RLS grant,
-- so `anon` stays granted nothing at the database level.
alter table public.clinics add column if not exists slug text;
create unique index if not exists idx_clinics_slug on public.clinics(slug);

-- Doctors now log in — this is the whole reason auth_id didn't exist
-- before. email is denormalized (also lives in auth.users) because the
-- anon-key client can never read auth.users directly; the admin's
-- doctor list and analytics need it without a service-role round trip.
alter table public.doctors add column if not exists auth_id uuid unique references auth.users(id) on delete set null;
alter table public.doctors add column if not exists email text;
alter table public.doctors add column if not exists must_change_password boolean not null default true;

-- doctor_id is nullable: a doctor being removed should not take their
-- patients' history down with them (on delete set null, not cascade).
alter table public.patients add column if not exists doctor_id uuid references public.doctors(id) on delete set null;
alter table public.patients add column if not exists email text;
alter table public.patients add column if not exists must_change_password boolean not null default true;
alter table public.patients add column if not exists onboarding_completed boolean not null default false;

create index if not exists idx_patients_doctor on public.patients(doctor_id);
create index if not exists idx_doctors_auth on public.doctors(auth_id);


-- Defined only now that doctors.auth_id exists. SECURITY DEFINER for the
-- same reason current_patient_id() is: policies need to resolve the
-- caller's OWN doctor row without recursing back into RLS on `doctors`.
create or replace function public.current_doctor_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select id from public.doctors where auth_id = auth.uid() limit 1;
$$;


-- ---------------------------------------------------------------------
-- Weekly availability -> bookable slots
--
-- The patient booking UI generates concrete slot times from these
-- recurring windows (against the clinic's timezone-naive local time,
-- matching how `appointments.slot` is already stored) and checks them
-- against existing appointments; this table only holds the recurring
-- rule, not materialized slots.
-- ---------------------------------------------------------------------

create table if not exists public.doctor_availability (
    id          uuid primary key default gen_random_uuid(),
    doctor_id   uuid not null references public.doctors(id) on delete cascade,
    clinic_id   uuid not null references public.clinics(id) on delete cascade,
    day_of_week smallint not null check (day_of_week between 0 and 6),
    start_time  time not null,
    end_time    time not null,
    created_at  timestamptz not null default now(),
    check (end_time > start_time)
);

create index if not exists idx_availability_doctor on public.doctor_availability(doctor_id);
create index if not exists idx_availability_clinic  on public.doctor_availability(clinic_id);

alter table public.doctor_availability enable row level security;


-- ---------------------------------------------------------------------
-- RLS changes
-- ---------------------------------------------------------------------

-- doctors — admin still adds/manages; a doctor may now update their own
-- row (status, clearing must_change_password on first login).
drop policy if exists doctors_self_update on public.doctors;
create policy doctors_self_update on public.doctors
    for update using (auth_id = auth.uid())
    with check (auth_id = auth.uid() and clinic_id = public.auth_clinic_id());


-- patients — write moves from admin to doctor (scoped to their own
-- patients), plus a patient self-update for onboarding/first-login state.
-- Admin KEEPS read (for analytics) but loses write entirely — no delete
-- policy exists for anyone, same as before.
--
-- patients_select ALSO needs the doctor branch added here, not just the
-- write policies: INSERT ... RETURNING (what registering a patient does)
-- implicitly re-checks the SELECT policy against the just-inserted row,
-- since returning it counts as reading it. Without this, the WITH CHECK
-- on the insert passes but the whole statement still fails RLS on the
-- RETURNING clause — found live, by actually registering a patient as a
-- doctor, not by inspecting the policy text.
drop policy if exists patients_select on public.patients;
create policy patients_select on public.patients
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_clinic_admin()
            or auth_id = auth.uid()
            or (public.is_doctor() and doctor_id = public.current_doctor_id())
        )
    );

drop policy if exists patients_admin_write on public.patients;

drop policy if exists patients_doctor_insert on public.patients;
create policy patients_doctor_insert on public.patients
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and doctor_id = public.current_doctor_id()
    );

drop policy if exists patients_write_update on public.patients;
create policy patients_write_update on public.patients
    for update using (
        clinic_id = public.auth_clinic_id()
        and (
            (public.is_doctor() and doctor_id = public.current_doctor_id())
            or auth_id = auth.uid()
        )
    )
    with check (
        clinic_id = public.auth_clinic_id()
        and (
            (public.is_doctor() and doctor_id = public.current_doctor_id())
            or auth_id = auth.uid()
        )
    );


-- documents / chunks / storage — write moves from admin to doctor
-- entirely, including verification: nothing else can own it once the
-- admin's scope is administrative-only.
drop policy if exists documents_admin_write on public.documents;
drop policy if exists documents_doctor_write on public.documents;
create policy documents_doctor_write on public.documents
    for all using (clinic_id = public.auth_clinic_id() and public.is_doctor())
    with check (clinic_id = public.auth_clinic_id() and public.is_doctor());

-- documents_select (0001) already reads `verified OR is_clinic_admin()`.
-- A doctor needs the same "see pending too" visibility admin had.
drop policy if exists documents_select on public.documents;
create policy documents_select on public.documents
    for select using (
        clinic_id = public.auth_clinic_id()
        and (public.is_doctor() or verified)
    );

drop policy if exists chunks_admin_write on public.chunks;
drop policy if exists chunks_doctor_write on public.chunks;
create policy chunks_doctor_write on public.chunks
    for all using (clinic_id = public.auth_clinic_id() and public.is_doctor())
    with check (clinic_id = public.auth_clinic_id() and public.is_doctor());

drop policy if exists chunks_select on public.chunks;
create policy chunks_select on public.chunks
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_doctor()
            or exists (
                select 1 from public.documents d
                where d.id = chunks.document_id and d.verified
            )
        )
    );


-- medical_records — narrows from "admin sees/writes all" to "doctor
-- sees/writes only their own patients' records". Admin loses this
-- entirely: medical content, not administrative.
drop policy if exists records_select on public.medical_records;
create policy records_select on public.medical_records
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            patient_id = public.current_patient_id()
            or (
                public.is_doctor()
                and exists (
                    select 1 from public.patients p
                    where p.id = medical_records.patient_id
                      and p.doctor_id = public.current_doctor_id()
                )
            )
        )
    );

drop policy if exists records_admin_write on public.medical_records;
drop policy if exists records_doctor_write on public.medical_records;
create policy records_doctor_write on public.medical_records
    for all using (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and exists (
            select 1 from public.patients p
            where p.id = medical_records.patient_id
              and p.doctor_id = public.current_doctor_id()
        )
    )
    with check (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and exists (
            select 1 from public.patients p
            where p.id = medical_records.patient_id
              and p.doctor_id = public.current_doctor_id()
        )
    );


-- appointments — add doctor read for appointments booked with them.
-- Deliberately NOT adding doctor write/update here: the spec asks for
-- "view appointments booked with them," not doctor-side cancellation —
-- flagged in the implementation plan as a likely near-term follow-up,
-- not assumed in now.
drop policy if exists appointments_select on public.appointments;
create policy appointments_select on public.appointments
    for select using (
        clinic_id = public.auth_clinic_id()
        and (
            public.is_clinic_admin()
            or patient_id = public.current_patient_id()
            or (public.is_doctor() and doctor_id = public.current_doctor_id())
        )
    );


-- doctor_availability — doctor manages their own; clinic-wide read since
-- patients need it to see bookable slots.
drop policy if exists availability_select on public.doctor_availability;
create policy availability_select on public.doctor_availability
    for select using (clinic_id = public.auth_clinic_id());

drop policy if exists availability_doctor_write on public.doctor_availability;
create policy availability_doctor_write on public.doctor_availability
    for all using (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and doctor_id = public.current_doctor_id()
    )
    with check (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and doctor_id = public.current_doctor_id()
    );


-- storage — same authority shift as documents/chunks.
drop policy if exists guidelines_admin_write on storage.objects;
drop policy if exists guidelines_doctor_write on storage.objects;
create policy guidelines_doctor_write on storage.objects
    for all using (
        bucket_id = 'guidelines'
        and (storage.foldername(name))[1] = public.auth_clinic_id()::text
        and public.is_doctor()
    )
    with check (
        bucket_id = 'guidelines'
        and (storage.foldername(name))[1] = public.auth_clinic_id()::text
        and public.is_doctor()
    );


-- ---------------------------------------------------------------------
-- Grants
--
-- "grant ... on all tables in schema public" only covers tables that
-- existed when it ran — doctor_availability didn't exist when 0001 ran
-- it, so it needs its own pass here, not an assumption that the earlier
-- grant already covers it.
-- ---------------------------------------------------------------------

grant select, insert, update, delete on all tables in schema public to authenticated;
grant execute on all functions in schema public to authenticated;
