# Clinical RAG Sources

## Source 1 — NICE

- Organization: National Institute for Health and Care Excellence (NICE)
- Guideline: NG28
- Title: Type 2 diabetes in adults: management
- Official URL: https://www.nice.org.uk/guidance/ng28
- Credibility: UK statutory body; NG28 is a formally issued, periodically
  updated national clinical guideline, not an informal publication.
- Public accessibility: Free, no registration required.

## Source 2 — WHO

- Organization: World Health Organization (WHO)
- Guideline: HEARTS-D
- Title: Diagnosis and management of type 2 diabetes
- Official URL: https://iris.who.int/handle/10665/331710
- Credibility: UN specialized health agency; HEARTS-D is part of WHO's
  formally published HEARTS technical package for primary care.
- Public accessibility: Free, no registration required, via the WHO IRIS
  repository.

Both URLs above match `SOURCE_METADATA` in `rag/ingest.py`, which is what actually
travels into every chunk's metadata and every citation a patient sees — keep the two
in sync if either source is replaced.
