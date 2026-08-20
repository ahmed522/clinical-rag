-- Structured, claim-level RAG evidence. All columns are additive so legacy
-- messages and clients remain valid during rollout.

alter table public.messages
    add column if not exists grounded boolean,
    add column if not exists reason text,
    add column if not exists evidence_strength text,
    add column if not exists evidence jsonb,
    add column if not exists prompt_version text,
    add column if not exists rag_metadata jsonb;

alter table public.messages
    drop constraint if exists messages_evidence_strength_check;
alter table public.messages
    add constraint messages_evidence_strength_check
    check (
        evidence_strength is null
        or evidence_strength in ('high', 'medium', 'low', 'insufficient')
    );

comment on column public.messages.evidence is
    'Structured recommendation, claim evidence, evidence checks, and safety notice.';
comment on column public.messages.rag_metadata is
    'Provider/model, retrieved chunk scores, verifier output, and stage latency audit.';

