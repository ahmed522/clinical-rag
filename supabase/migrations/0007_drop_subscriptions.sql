-- Subscriptions were scaffolded for a premium consult mode that was removed
-- in 0006. No application or RAG path reads this table, so retaining it adds
-- unused schema and policies without providing a product capability.

drop table if exists public.subscriptions;
