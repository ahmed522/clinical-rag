"""
Turns retrieved chunks into a grounded, cited answer — or into an honest
refusal.

Three independent checks stand between a question and an answer, so no
single failure produces ungrounded medical text:

  1. Retrieval gate    — nothing relevant retrieved, no LLM call at all.
  2. LLM judgment      — the model must declare `sufficient`; it is
                         instructed to refuse rather than fill gaps.
  3. Citation validation — every citation must point at a chunk that was
                         actually retrieved. Checked mechanically here,
                         not trusted from the model.

Check 3 matters because it is the only one that does not depend on the
model behaving. A model that invents a citation, or cites a source it was
never given, is caught by code.
"""

from typing import List, Optional, Tuple

from app.llm import get_provider
from app.llm_prompts import fallback_text, system_prompt
from app.services.retrieval import retrieve


class GroundedAnswer:
    def __init__(
        self,
        text: str,
        citations: Optional[List[dict]] = None,
        grounded: bool = True,
        reason: Optional[str] = None,
    ):
        self.text = text
        self.citations = citations or []
        self.grounded = grounded
        self.reason = reason


def _validate_citations(cited: List[int], sources: List[dict]) -> Tuple[List[dict], List[int]]:
    """
    Keep only citations that point at a source actually retrieved.

    Returns (resolved citations, rejected indices). Indices are 1-based to
    match how sources are numbered in the prompt.
    """
    resolved, rejected = [], []

    for number in cited:
        if 1 <= number <= len(sources):
            source = sources[number - 1]
            resolved.append(
                {
                    "document": source["title"],
                    "page": source.get("page_number"),
                    "section": source.get("section_title"),
                }
            )
        else:
            rejected.append(number)

    return resolved, rejected


def answer_question(
    clinic_id: str,
    question: str,
    mode: str = "general",
    patient_context: str = "",
    persist_dir=None,
) -> GroundedAnswer:
    sources = retrieve(clinic_id, question, persist_dir=persist_dir)

    # Check 1 — nothing to ground an answer in. Do not call the LLM: with
    # no sources it can only draw on its own training, which is precisely
    # the ungrounded medical claim the product must never make.
    if not sources:
        return GroundedAnswer(
            fallback_text(mode),
            grounded=False,
            reason="no_relevant_sources",
        )

    result = get_provider().complete(
        system=system_prompt(mode),
        sources=sources,
        question=question,
        context=patient_context,
    )

    # Check 2 — the model itself reports it cannot answer from the sources.
    if not result.sufficient or not result.answer:
        return GroundedAnswer(
            fallback_text(mode),
            grounded=False,
            reason="model_reported_insufficient_context",
        )

    # Check 3 — citations must resolve to retrieved sources.
    citations, rejected = _validate_citations(result.citations, sources)

    if rejected:
        # A citation pointing at a source that was never supplied means the
        # answer is not traceable. Refuse rather than show a clinical claim
        # with a broken provenance trail.
        return GroundedAnswer(
            fallback_text(mode),
            grounded=False,
            reason=f"invalid_citations:{rejected}",
        )

    if not citations:
        # An answer with no citation cannot be checked by a clinician,
        # which defeats the purpose of grounding it.
        return GroundedAnswer(
            fallback_text(mode),
            grounded=False,
            reason="no_citations_returned",
        )

    return GroundedAnswer(result.answer, citations=citations, grounded=True)
