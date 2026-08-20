-- Persisted, doctor-owned clinical-assistant conversations.
-- Patient chat tables remain patient-owned; doctors cannot read them.

create table if not exists public.doctor_chat_sessions (
    id uuid primary key default gen_random_uuid(),
    clinic_id uuid not null references public.clinics(id) on delete cascade,
    doctor_id uuid not null references public.doctors(id) on delete cascade,
    started_at timestamptz not null default now()
);

create table if not exists public.doctor_chat_messages (
    id uuid primary key default gen_random_uuid(),
    clinic_id uuid not null references public.clinics(id) on delete cascade,
    session_id uuid not null references public.doctor_chat_sessions(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    citations jsonb,
    grounded boolean,
    reason text,
    evidence_strength text check (evidence_strength in ('high', 'medium', 'low', 'insufficient')),
    evidence jsonb,
    prompt_version text,
    rag_metadata jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_doctor_chat_sessions_doctor
    on public.doctor_chat_sessions(doctor_id, started_at desc);
create index if not exists idx_doctor_chat_messages_session
    on public.doctor_chat_messages(session_id, created_at);

alter table public.doctor_chat_sessions enable row level security;
alter table public.doctor_chat_messages enable row level security;

drop policy if exists doctor_chat_sessions_select on public.doctor_chat_sessions;
create policy doctor_chat_sessions_select on public.doctor_chat_sessions
    for select using (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and doctor_id = public.current_doctor_id()
    );

drop policy if exists doctor_chat_sessions_insert on public.doctor_chat_sessions;
create policy doctor_chat_sessions_insert on public.doctor_chat_sessions
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and doctor_id = public.current_doctor_id()
    );

drop policy if exists doctor_chat_messages_select on public.doctor_chat_messages;
create policy doctor_chat_messages_select on public.doctor_chat_messages
    for select using (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and exists (
            select 1 from public.doctor_chat_sessions s
            where s.id = doctor_chat_messages.session_id
              and s.doctor_id = public.current_doctor_id()
              and s.clinic_id = public.auth_clinic_id()
        )
    );

drop policy if exists doctor_chat_messages_insert on public.doctor_chat_messages;
create policy doctor_chat_messages_insert on public.doctor_chat_messages
    for insert with check (
        clinic_id = public.auth_clinic_id()
        and public.is_doctor()
        and exists (
            select 1 from public.doctor_chat_sessions s
            where s.id = doctor_chat_messages.session_id
              and s.doctor_id = public.current_doctor_id()
              and s.clinic_id = public.auth_clinic_id()
        )
    );

grant select, insert on public.doctor_chat_sessions to authenticated;
grant select, insert on public.doctor_chat_messages to authenticated;
