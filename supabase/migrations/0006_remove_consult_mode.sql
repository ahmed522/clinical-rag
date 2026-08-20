-- 0006_remove_consult_mode.sql
--
-- Removes the "consult" chat mode, leaving two modes: general information
-- and urgent triage.
--
-- Consult was intended as the premium tier but was never gated, so the mode
-- was free to every patient and only duplicated General with the patient's
-- own records injected for relevance. Triage still injects that same
-- context, so this narrows the product surface, not the data reaching the
-- model.
--
-- Existing consult sessions are relabelled rather than deleted: they carry
-- real messages, and rewriting the label is non-destructive where a cascade
-- delete would not be. "general" is now the only truthful description of
-- what those sessions were.

-- 1. Relabel before tightening, or the new constraint cannot be validated.
update public.chat_sessions
   set mode = 'general'
 where mode = 'consult';

-- 2. Replace the mode check. Dropped by name (confirmed as the generated
--    chat_sessions_mode_check) and re-added, since Postgres has no
--    "alter check constraint".
alter table public.chat_sessions
    drop constraint if exists chat_sessions_mode_check;

alter table public.chat_sessions
    add constraint chat_sessions_mode_check
    check (mode in ('general', 'triage'));
