"""Grounded answer orchestration with claim-level evidence and fail-closed checks."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.llm import LLMResult, get_provider
from app.llm_prompts import (
    DEPENDENCY_UNAVAILABLE_FALLBACK,
    PROMPT_VERSION,
    fallback_text,
    system_prompt,
)
from app.services.retrieval import RetrievalUnavailableError, retrieve
from app.services.safety import personal_clinical_request


logger = logging.getLogger(__name__)


SAFETY_NOTICE = (
    "This answer summarizes the clinic's verified sources. It supports, but does "
    "not replace, clinical judgment or an in-person assessment."
)

# One retry for generation-side excerpt flakiness (see answer_question).
# Not model judgment — every attempt is still mechanically re-verified.
GENERATION_MAX_ATTEMPTS = 2

RATE_LIMITED_FALLBACK = (
    "The clinic's assistant is handling too many questions right now. Please wait "
    "a moment and ask again."
)


def _is_rate_limit(exc: Exception) -> bool:
    """Rate limiting is transient and user-actionable; other faults are not."""
    if type(exc).__name__ in {"RateLimitError", "TooManyRequests"}:
        return True
    return getattr(exc, "status_code", None) == 429


class GroundedAnswer:
    def __init__(
        self,
        text: str,
        citations: Optional[List[dict]] = None,
        grounded: bool = True,
        reason: Optional[str] = None,
        evidence: Optional[dict] = None,
        audit: Optional[dict] = None,
    ):
        self.text = text
        self.citations = citations or []
        self.grounded = grounded
        self.reason = reason
        self.evidence = evidence
        self.audit = audit or {}

    @property
    def evidence_strength(self) -> Optional[str]:
        return self.evidence.get("evidence_strength") if self.evidence else None


# Lookalike punctuation the model routinely substitutes when it "quotes"
# source text — e.g. it renders every hyphen as U+2011 (non-breaking
# hyphen) regardless of what the PDF actually used, which fails a naive
# byte-exact substring check even though the quote is otherwise verbatim.
# Folding both sides to ASCII before comparing is a display-equivalence
# normalization, not a content change: it does not let through any text
# the source doesn't contain, so the "exact excerpt" guarantee still holds.
_PUNCTUATION_FOLD = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    " ": " ", " ": " ", " ": " ",
})


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.translate(_PUNCTUATION_FOLD)).strip()


def _safe_url(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.lower().startswith(("https://", "http://")):
        return value
    return None


def _source_label(source: dict) -> str:
    label = str(source.get("title") or "Verified clinic document")
    if source.get("page_number"):
        label += f" (p. {source['page_number']})"
    return label


def _checked_sources(sources: List[dict]) -> List[str]:
    seen, labels = set(), []
    for source in sources:
        label = _source_label(source)
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _refusal(
    *,
    text: str,
    reason: str,
    sources: Optional[List[dict]] = None,
    missing_evidence: str = "",
    audit: Optional[dict] = None,
) -> GroundedAnswer:
    checked = _checked_sources(sources or [])
    evidence = {
        "recommendation": text,
        "recommendation_claims": [],
        "supporting_evidence": [],
        "evidence_strength": "insufficient",
        "safety_notice": SAFETY_NOTICE,
        "evidence_checked": checked,
        "missing_evidence": missing_evidence
        or "A clinic-approved source that directly and specifically supports the requested answer.",
        "checks": {
            "retrieval_passed": bool(sources),
            "exact_excerpts_passed": False,
            "citation_coverage": 0.0,
            "evidence_match_passed": False,
            "safety_passed": reason not in {
                "patient_specific_diagnosis",
                "patient_specific_dosage_or_treatment",
            },
            "verifier_passed": False,
        },
    }
    return GroundedAnswer(
        text,
        grounded=False,
        reason=reason,
        evidence=evidence,
        audit={**(audit or {}), "failure_reason": reason},
    )


def _personal_request_refusal(reason: str, mode: str) -> GroundedAnswer:
    if mode == "triage":
        text = (
            "I can't diagnose you or choose a dose or treatment for your individual case. "
            "If your symptoms are severe, getting worse, or worrying you, seek urgent "
            "in-person or emergency care now. Otherwise, contact the clinic for a clinician "
            "who can assess your history safely."
        )
    else:
        text = (
            "I can summarize general information from the clinic's verified guidance, but I "
            "can't diagnose you or recommend a dose or treatment for your individual case. "
            "Please ask your doctor or the clinic, because they can consider your examination, "
            "medical history, medicines, and test results."
        )
    return _refusal(
        text=text,
        reason=reason,
        missing_evidence="Patient-specific clinical assessment cannot be established from uploaded guidance alone.",
    )


def validate_claims(
    result: LLMResult,
    sources: List[dict],
) -> Tuple[Optional[dict], List[dict], List[dict], List[str]]:
    """Resolve source IDs and exact excerpts into an auditable answer package."""
    errors: List[str] = []
    citations: List[dict] = []
    citation_keys: Dict[Tuple[int, str], str] = {}
    verifier_claims: List[dict] = []
    recommendation_claims: List[dict] = []
    supporting_claims: List[dict] = []

    grouped = (
        ("recommendation", result.recommendation_claims, recommendation_claims),
        ("supporting", result.supporting_claims, supporting_claims),
    )
    for kind, claims, resolved_group in grouped:
        for index, claim in enumerate(claims, start=1):
            claim_id = f"{kind}-{index}"
            claim_text = _normalize(claim.text)
            if not claim_text or len(claim_text) > 1200:
                errors.append(f"{claim_id}:invalid_claim_text")
                continue
            if not claim.evidence:
                errors.append(f"{claim_id}:missing_evidence")
                continue

            citation_ids: List[str] = []
            excerpts_for_verifier: List[dict] = []
            for reference in claim.evidence:
                if not 1 <= reference.source_id <= len(sources):
                    errors.append(f"{claim_id}:invalid_source_id:{reference.source_id}")
                    continue
                excerpt = _normalize(reference.excerpt)
                source = sources[reference.source_id - 1]
                source_text = _normalize(str(source.get("text") or ""))
                if len(excerpt) < 8 or len(excerpt) > 600 or excerpt not in source_text:
                    errors.append(f"{claim_id}:invented_or_invalid_excerpt:{reference.source_id}")
                    continue

                key = (reference.source_id, excerpt)
                citation_id = citation_keys.get(key)
                if citation_id is None:
                    citation_id = f"C{len(citations) + 1}"
                    citation_keys[key] = citation_id
                    citations.append(
                        {
                            "id": citation_id,
                            "source_id": reference.source_id,
                            "rank": source.get("rank", reference.source_id),
                            "document_id": source.get("document_id"),
                            "document": source.get("title") or "Unknown document",
                            "publisher": source.get("publisher"),
                            "page": source.get("page_number"),
                            "section": source.get("section_title"),
                            "chunk_id": source.get("chunk_id"),
                            "source_url": _safe_url(source.get("source_url")),
                            "excerpt": excerpt,
                            "vector_distance": source.get("distance"),
                            "rerank_score": source.get("rerank_score"),
                        }
                    )
                if citation_id not in citation_ids:
                    citation_ids.append(citation_id)
                    excerpts_for_verifier.append({"citation_id": citation_id, "text": excerpt})

            if not citation_ids:
                errors.append(f"{claim_id}:no_valid_citations")
                continue
            resolved = {"claim_id": claim_id, "text": claim_text, "citation_ids": citation_ids}
            resolved_group.append(resolved)
            verifier_claims.append(
                {
                    "claim_id": claim_id,
                    "kind": kind,
                    "claim": claim_text,
                    "excerpts": excerpts_for_verifier,
                }
            )

    # A claim-level failure (an invented excerpt, a bad source id) must not
    # discard SIBLING claims that independently passed the same exact-quote
    # check — each surviving claim is still verified on its own merits by
    # the LLM evidence audit below. Only refuse outright when nothing
    # survived: zero recommendation claims means there is nothing safe to
    # show a patient regardless of what supporting evidence remains.
    if not recommendation_claims:
        errors.append("missing_recommendation")
        return None, [], verifier_claims, errors

    def render(claim: dict) -> str:
        markers = " ".join(f"[{citation_id}]" for citation_id in claim["citation_ids"])
        return f"{claim['text']} {markers}".strip()

    recommendation = "\n\n".join(render(claim) for claim in recommendation_claims)
    missing_evidence = result.missing_evidence if result.partial else ""
    if errors:
        dropped_note = "Some generated statements could not be matched to exact source text and were excluded."
        missing_evidence = f"{missing_evidence} {dropped_note}".strip()
    package = {
        "recommendation": recommendation,
        "recommendation_claims": recommendation_claims,
        "supporting_evidence": [
            {"claim_id": claim["claim_id"], "claim": claim["text"], "citation_ids": claim["citation_ids"]}
            for claim in supporting_claims
        ],
        "evidence_strength": "low" if (result.partial or errors) else "medium",
        "safety_notice": SAFETY_NOTICE,
        "evidence_checked": _checked_sources(sources),
        "missing_evidence": missing_evidence,
        "checks": {
            "retrieval_passed": True,
            "exact_excerpts_passed": not errors,
            "citation_coverage": 1.0,
            "evidence_match_passed": False,
            "safety_passed": False,
            "verifier_passed": False,
        },
    }
    return package, citations, verifier_claims, errors


def verification_failure(verification, expected_ids: set[str]) -> Tuple[bool, List[dict]]:
    rows = [
        {
            "claim_id": row.claim_id,
            "supported": row.supported,
            "relevant": row.relevant,
            "safe": row.safe,
            "overconfident": row.overconfident,
            "reason": row.reason,
        }
        for row in verification.results
    ]
    ids = [row["claim_id"] for row in rows]
    complete = set(ids) == expected_ids and len(ids) == len(expected_ids)
    passed = complete and all(
        row["supported"] and row["relevant"] and row["safe"] and not row["overconfident"]
        for row in rows
    )
    return not passed, rows


def _strength(package: dict, citations: List[dict], partial: bool) -> str:
    if partial:
        return "low"
    by_id = {citation["id"]: citation for citation in citations}
    for claim in package["recommendation_claims"]:
        locations = {
            (by_id[citation_id].get("chunk_id"), by_id[citation_id].get("page"))
            for citation_id in claim["citation_ids"]
        }
        if len(locations) < 2:
            return "medium"
    return "high"


def answer_question(
    clinic_id: str,
    question: str,
    mode: str = "general",
    patient_context: str = "",
    persist_dir=None,
    document_ids: Optional[List[str]] = None,
) -> GroundedAnswer:
    total_started = perf_counter()
    safety_reason = personal_clinical_request(question)
    if safety_reason:
        answer = _personal_request_refusal(safety_reason, mode)
        answer.audit["latency_ms"] = {"total": round((perf_counter() - total_started) * 1000, 2)}
        return answer

    retrieval_started = perf_counter()
    try:
        sources = retrieve(
            clinic_id,
            question,
            persist_dir=persist_dir,
            document_ids=document_ids,
        )
    except RetrievalUnavailableError:
        return _refusal(
            text=DEPENDENCY_UNAVAILABLE_FALLBACK,
            reason="retrieval_unavailable",
            missing_evidence="The clinic knowledge index could not be accessed.",
            audit={"latency_ms": {"total": round((perf_counter() - total_started) * 1000, 2)}},
        )
    retrieval_ms = (perf_counter() - retrieval_started) * 1000

    if not sources:
        return _refusal(
            text=fallback_text(mode),
            reason="no_relevant_sources",
            missing_evidence="No verified clinic source directly addressing this question was retrieved.",
            audit={"latency_ms": {"retrieval": round(retrieval_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
        )

    provider = get_provider()
    audit = {
        "provider": getattr(provider, "name", provider.__class__.__name__),
        "model": getattr(provider, "model", None),
        "prompt_version": PROMPT_VERSION,
        "retrieved": [
            {
                "rank": source.get("rank"),
                "chunk_id": source.get("chunk_id"),
                "document_id": source.get("document_id"),
                "page": source.get("page_number"),
                "vector_distance": source.get("distance"),
                "rerank_score": source.get("rerank_score"),
            }
            for source in sources
        ],
    }

    # Groq's inference is not reliably deterministic even at temperature 0
    # (observed live: the identical prompt sometimes returns an exact
    # verbatim excerpt and sometimes a paraphrase that fails the mechanical
    # quote check). That is generation flakiness, not a judgment that the
    # sources are insufficient, so it gets one bounded retry here — the
    # exact-quote and evidence-audit checks below are unchanged and still
    # apply to whichever attempt survives; retrying never relaxes them.
    generation_ms = 0.0
    package = citations = verifier_claims = None
    validation_errors: List[str] = []
    for attempt in range(GENERATION_MAX_ATTEMPTS):
        generation_started = perf_counter()
        try:
            result = provider.complete(
                system=system_prompt(mode),
                sources=sources,
                question=question,
                context=patient_context,
            )
        except Exception as exc:
            rate_limited = _is_rate_limit(exc)
            logger.warning(
                "generation failed (%s): %s: %s",
                "rate_limited" if rate_limited else "unavailable",
                type(exc).__name__,
                exc,
            )
            return _refusal(
                text=RATE_LIMITED_FALLBACK if rate_limited else DEPENDENCY_UNAVAILABLE_FALLBACK,
                reason="generation_rate_limited" if rate_limited else "generation_unavailable",
                sources=sources,
                missing_evidence=(
                    "The assistant reached its request limit before it could inspect the evidence."
                    if rate_limited
                    else "The answer generator could not inspect the retrieved evidence."
                ),
                audit={**audit, "latency_ms": {"retrieval": round(retrieval_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
            )
        generation_ms += (perf_counter() - generation_started) * 1000

        if not result.sufficient:
            return _refusal(
                text=fallback_text(mode),
                reason="model_reported_insufficient_context",
                sources=sources,
                missing_evidence=result.missing_evidence,
                audit={**audit, "latency_ms": {"retrieval": round(retrieval_ms, 2), "generation": round(generation_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
            )

        package, citations, verifier_claims, validation_errors = validate_claims(result, sources)
        if package is not None or attempt == GENERATION_MAX_ATTEMPTS - 1:
            break

    audit["validation_errors"] = validation_errors
    # package is None only when every recommendation claim independently
    # failed validation on every attempt — a claim-level error with
    # surviving siblings already produced a package above and proceeds to
    # verification below, rather than discarding claims that passed their
    # own exact-quote check.
    if package is None:
        logger.info("claim validation failed after %d attempts: %s", GENERATION_MAX_ATTEMPTS, validation_errors)
        return _refusal(
            text=fallback_text(mode),
            reason="evidence_validation_failed",
            sources=sources,
            missing_evidence="The generated claims could not be mapped to exact excerpts in the retrieved chunks.",
            audit={
                **audit,
                "latency_ms": {"retrieval": round(retrieval_ms, 2), "generation": round(generation_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)},
            },
        )

    if not settings.EVIDENCE_VERIFIER_ENABLED:
        return _refusal(
            text=DEPENDENCY_UNAVAILABLE_FALLBACK,
            reason="evidence_verifier_disabled",
            sources=sources,
            missing_evidence="The mandatory evidence-support verifier is disabled.",
            audit=audit,
        )

    verification_started = perf_counter()
    try:
        verification = provider.verify(question=question, claims=verifier_claims)
    except Exception as exc:
        rate_limited = _is_rate_limit(exc)
        logger.warning(
            "evidence verification failed (%s): %s: %s",
            "rate_limited" if rate_limited else "unavailable",
            type(exc).__name__,
            exc,
        )
        return _refusal(
            text=RATE_LIMITED_FALLBACK if rate_limited else DEPENDENCY_UNAVAILABLE_FALLBACK,
            reason="evidence_verification_rate_limited" if rate_limited else "evidence_verification_unavailable",
            sources=sources,
            missing_evidence="The retrieved evidence could not be independently verified.",
            audit={**audit, "latency_ms": {"retrieval": round(retrieval_ms, 2), "generation": round(generation_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
        )
    verification_ms = (perf_counter() - verification_started) * 1000
    failed, verification_rows = verification_failure(
        verification, {claim["claim_id"] for claim in verifier_claims}
    )
    audit["verification"] = verification_rows
    if failed:
        return _refusal(
            text=fallback_text(mode),
            reason="evidence_verification_failed",
            sources=sources,
            missing_evidence="At least one generated claim was not directly supported, relevant, and clinically safe.",
            audit={**audit, "latency_ms": {"retrieval": round(retrieval_ms, 2), "generation": round(generation_ms, 2), "verification": round(verification_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
        )

    package["checks"].update(
        {"evidence_match_passed": True, "safety_passed": True, "verifier_passed": True}
    )
    package["evidence_strength"] = _strength(package, citations, result.partial)
    audit["citation_coverage"] = 1.0
    audit["latency_ms"] = {
        "retrieval": round(retrieval_ms, 2),
        "generation": round(generation_ms, 2),
        "verification": round(verification_ms, 2),
        "total": round((perf_counter() - total_started) * 1000, 2),
    }
    return GroundedAnswer(
        package["recommendation"],
        citations=citations,
        grounded=True,
        evidence=package,
        audit=audit,
    )
