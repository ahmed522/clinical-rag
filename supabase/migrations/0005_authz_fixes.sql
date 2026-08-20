-- Authorization fixes found in code review of the three-role rollout
-- (0002/0003). All changes are additive/corrective RLS — no data is
-- dropped or backfilled destructively.

-- ---------------------------------------------------------------------
-- 1. A patient could reassign their own doctor_id via patients_write_update
--    (the auth_id = auth.uid() branch was column-unrestricted), which then
--    handed medical_records access to whichever doctor they named — RLS
--    has no column-level WITH CHECK, so this is enforced with a trigger.
-- ---------------------------------------------------------------------

create or replace function public.patients_self_update_guard()
returns trigger
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
    if auth.uid() = old.auth_id and not public.is_doctor() and not public.is_clinic_admin() then
        if new.doctor_id is distinct from old.doctor_id
            or new.clinic_id is distinct from old.clinic_id
            or new.auth_id is distinct from old.auth_id
        then
            raise exception 'Patients cannot change doctor_id, clinic_id, or auth_id';
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists patients_self_update_guard on public.patients;
create trigger patients_self_update_guard
    before update on public.patients
    for each row
    execute function public.patients_self_update_guard();


-- ---------------------------------------------------------------------
-- 2. guidelines_read (Storage) still granted any authenticated clinic
--    member read access to every object in their clinic's folder, even
--    though 0003 made "status = 'ready' AND verified" the row-level
--    definition of a patient-visible document. Storage objects are keyed
--    {clinic_id}/{document_id}.pdf, so the document_id is recoverable
--    from the object name to join back to that same rule.
-- ---------------------------------------------------------------------

drop policy if exists guidelines_read on storage.objects;
create policy guidelines_read on storage.objects
    for select using (
        bucket_id = 'guidelines'
        and (storage.foldername(name))[1] = public.auth_clinic_id()::text
        and (
            public.is_doctor()
            or exists (
                select 1
                from public.documents d
                where d.clinic_id = public.auth_clinic_id()
                  and d.status = 'ready'
                  and d.verified
                  and name = d.clinic_id::text || '/' || d.id::text || '.pdf'
            )
        )
    );


-- ---------------------------------------------------------------------
-- 3. clinics.slug was left nullable with no backfill; any clinic created
--    before 0002 has no reachable /clinic/{slug} entry point and 404s
--    with no diagnostic. Backfill from name, then enforce not null.
-- ---------------------------------------------------------------------

do $$
declare
    row_record record;
    candidate text;
    suffix int;
begin
    for row_record in select id, name from public.clinics where slug is null loop
        candidate := trim(both '-' from regexp_replace(lower(row_record.name), '[^a-z0-9]+', '-', 'g'));
        if candidate = '' then
            candidate := 'clinic';
        end if;
        suffix := 2;
        while exists (select 1 from public.clinics where slug = candidate and id <> row_record.id) loop
            candidate := candidate || '-' || suffix;
            suffix := suffix + 1;
        end loop;
        update public.clinics set slug = candidate where id = row_record.id;
    end loop;
end $$;

alter table public.clinics alter column slug set not null;


-- ---------------------------------------------------------------------
-- 4. appointments_insert/appointments_update still granted clinic_admin
--    write, left over from the pre-doctor-role admin-does-everything
--    model. The 0002 header states the admin is administrative only;
--    every sibling policy (patients, documents, chunks, medical_records,
--    storage) was already narrowed. Scheduling belongs to the patient
--    booking for themselves; admin keeps read only, same as patients/
--    documents/medical_records.
-- ---------------------------------------------------------------------

drop policy if exists appointments_insert on public.appointments;
create policy appointments_insert on public.appointments
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and patient_id = public.current_patient_id()
    );

drop policy if exists appointments_update on public.appointments;
create policy appointments_update on public.appointments
    for update using (
        clinic_id = public.auth_clinic_id()
        and patient_id = public.current_patient_id()
    )
    with check (
        clinic_id = public.auth_clinic_id()
        and patient_id = public.current_patient_id()
    );


-- ---------------------------------------------------------------------
-- 5. Doctor's appointments tab lists all statuses, not just 'booked' —
--    idx_appointments_doctor_slot is partial on status='booked' and
--    cannot serve that scan.
-- ---------------------------------------------------------------------

create index if not exists idx_appointments_clinic_doctor
    on public.appointments(clinic_id, doctor_id);
