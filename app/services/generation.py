"""Grounded answer orchestration with claim-level evidence and fail-closed checks."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.llm import (
    ClaimVerification,
    EvidenceReference,
    GeneratedClaim,
    LLMResult,
    VerificationResult,
    get_provider,
)
from app.llm_prompts import (
    DEPENDENCY_UNAVAILABLE_FALLBACK,
    PROMPT_VERSION,
    fallback_text,
    get_system_prompt,
)
from app.services.retrieval import RetrievalUnavailableError, retrieve
from app.services.safety import personal_clinical_request
from rag.config import (
    ABSURD_DISTANCE,
    DOCTOR_RETRIEVAL_DISTANCE_GATE,
    DOCTOR_RETRIEVAL_K,
)


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

DOCTOR_INSUFFICIENT_EVIDENCE_FALLBACK = (
    "The clinic's verified guidance retrieved for this question does not establish "
    "a single guideline-backed answer. No clinical recommendation is being displayed. "
    "Review the cited guideline context and apply your professional judgment."
)

# This is not a medical classifier and never authorizes an answer. It catches
# unmistakably non-clinical requests before they can consume retrieval or be
# accidentally paired with a generic guideline sentence by a noisy model.
_CLEARLY_NON_MEDICAL = re.compile(
    r"\b(?:car|toyota|vehicle|oil\s+filter|engine|tyre|tire|recipe|pizza|"
    r"weather|football|movie|music|bitcoin|cryptocurrency|programming|code|"
    r"wifi|password|capital\s+of|holiday|flight)\b",
    re.IGNORECASE,
)


def _insufficient_evidence_text(role: str, mode: str) -> str:
    """Keep patient wording patient-safe and make clinician refusals role-appropriate."""
    if role == "doctor":
        return DOCTOR_INSUFFICIENT_EVIDENCE_FALLBACK
    return fallback_text(mode)


def _is_rate_limit(exc: Exception) -> bool:
    """Rate limiting is transient and user-actionable; other faults are not."""
    if type(exc).__name__ in {"RateLimitError", "TooManyRequests"}:
        return True
    return getattr(exc, "status_code", None) == 429


def _clearly_non_medical_question(question: str) -> bool:
    return bool(_CLEARLY_NON_MEDICAL.search(question))


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


def normalize_text(value: str) -> str:
    """Fold typographic punctuation and whitespace before any excerpt comparison.

    Public because the exact-excerpt check is only meaningful when BOTH sides
    are folded the same way. Clinical PDFs are full of non-breaking hyphens and
    en dashes -- NG28 writes "self-monitoring" with U+2011 and "1-3 months" with
    U+2013 -- which a model reproduces as plain ASCII. Comparing a folded
    excerpt against raw source text therefore rejects quotes that are in fact
    verbatim. scripts/evaluate_rag.py must reuse this rather than re-implement
    it, or the evaluation under-reports grounding.
    """
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


def _doctor_personal_request_refusal(reason: str) -> GroundedAnswer:
    """Keep clinician answers useful without making the model the prescriber."""
    return _refusal(
        text=(
            "I can summarize the clinic's verified guideline criteria, dosing ranges, "
            "contraindications, and monitoring requirements, but I can't diagnose an "
            "individual patient or select their treatment or dose. Rephrase the question "
            "as a general guideline question, then apply the cited guidance using the "
            "patient's complete clinical assessment and your professional judgment."
        ),
        reason=reason,
        missing_evidence=(
            "An uploaded guideline cannot establish the complete patient-specific clinical "
            "context required for an individual diagnosis or prescribing decision."
        ),
    )


def _doctor_extractive_rescue(sources: List[dict], question: str) -> LLMResult:
    """Create a citation-safe last resort for a formatting-only model failure.

    This does not make a medical inference.  It presents one exact sentence
    from the already reranked source to the independent verifier, which still
    decides whether it is relevant to the doctor's question.  It is deliberately
    doctor-only: the clinician can read the source wording and audit its
    citation, while a patient should never receive a raw guideline fallback.
    """
    question_words = {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]{3,}", question)
        if word.lower() not in {
            "about", "after", "before", "does", "from", "have", "into", "should",
            "that", "the", "this", "what", "when", "which", "with", "would",
        }
    }
    asks_for_initial_choice = not bool(
        re.search(r"\b(?:further|add(?:ing)?|escalat(?:e|ion)|intensif(?:y|ication)|next)\b", question, re.I)
    )
    candidates: List[Tuple[float, int, int, int, str]] = []
    for source_id, source in enumerate(sources, start=1):
        raw = str(source.get("text") or "").strip()
        source_has_sentence = False
        # Keep sentence boundaries in the original text; normalization happens
        # later in validate_claims before the exact-substring comparison.
        for position, sentence in enumerate(re.split(r"(?<=[.!?])\s+", raw)):
            sentence = sentence.strip()
            if not 24 <= len(sentence) <= 600:
                continue
            source_has_sentence = True
            overlap = len(question_words & set(re.findall(r"[A-Za-z0-9]{3,}", sentence.lower())))
            # The cross-encoder has already read the whole passage in relation
            # to the question. Prefer it over word overlap, which otherwise
            # favors a stray occurrence of "diagnosis" over the actual
            # recommendation section.
            rerank_score = float(source.get("rerank_score") or -1000.0)
            # "Further medicines" passages are valuable only when the doctor
            # actually asks about escalation. Without that qualifier, prefer
            # an initial-treatment passage that directly answers the question.
            if asks_for_initial_choice and re.search(r"\bfurther medicines?\b", sentence, re.I):
                rerank_score -= 2.0
            candidates.append((rerank_score, overlap, -source_id, -position, sentence))
        if not source_has_sentence:
            # Tables and OCR-derived bullet lists are often a single long line
            # without terminal punctuation. Preserve a source window for this
            # passage even if another passage did contain a sentence; otherwise
            # a higher-scoring table with the actual answer can never win.
            window = normalize_text(str(source.get("text") or ""))[:600]
            if " " in window:
                window = window.rsplit(" ", 1)[0]
            if len(window) >= 24:
                overlap = len(question_words & set(re.findall(r"[A-Za-z0-9]{3,}", window.lower())))
                rerank_score = float(source.get("rerank_score") or -1000.0)
                if asks_for_initial_choice and re.search(r"\bfurther medicines?\b", window, re.I):
                    rerank_score -= 2.0
                candidates.append((rerank_score, overlap, -source_id, 0, window))
    if not candidates:
        return LLMResult(sufficient=False, missing_evidence="Retrieved passages contain no quotable clinical statement.")

    # A source has already passed hybrid retrieval.  Overlap merely chooses the
    # most query-specific sentence; the verifier remains the authority on both
    # relevance and semantic support.
    _rerank_score, _overlap, negative_source_id, _position, excerpt = max(candidates)
    source_id = -negative_source_id
    return LLMResult(
        sufficient=True,
        recommendation_claims=[
            # The only added words identify the quote.  The clinical content is
            # exact source text and is independently verified before display.
            GeneratedClaim(
                text=f"The verified guideline states: {normalize_text(excerpt)}",
                evidence=[EvidenceReference(source_id, excerpt)],
            )
        ],
    )


def _local_extractive_verification(
    verifier_claims: List[dict], citations: List[dict]
) -> VerificationResult:
    """Verify a provider-outage extractive fallback without medical inference.

    This is deliberately narrower than the hosted semantic verifier. It only
    accepts the server-created *exact quotation* form, and only where the
    existing cross-encoder assigned a positive query-to-passage relevance
    score. Therefore it cannot approve generated/paraphrased clinical advice,
    and unrelated questions (which score strongly negative) remain refused.
    """
    citation_scores = {
        citation["id"]: citation.get("rerank_score")
        for citation in citations
    }
    rows: List[ClaimVerification] = []
    prefix = "The verified guideline states: "
    for claim in verifier_claims:
        excerpts = claim.get("excerpts") or []
        exact_quote = (
            claim.get("kind") == "recommendation"
            and len(excerpts) == 1
            and str(claim.get("claim") or "").startswith(prefix)
            and normalize_text(str(claim["claim"])[len(prefix):])
            == normalize_text(str(excerpts[0].get("text") or ""))
        )
        score = citation_scores.get(excerpts[0].get("citation_id")) if excerpts else None
        relevant = isinstance(score, (int, float)) and float(score) > 0.0
        passed = exact_quote and relevant
        rows.append(
            ClaimVerification(
                claim_id=claim["claim_id"],
                supported=passed,
                relevant=passed,
                safe=passed,
                overconfident=False,
                reason=(
                    "Exact clinic-source quotation with positive cross-encoder relevance."
                    if passed
                    else "The exact quotation did not meet the local relevance requirement."
                ),
            )
        )
    return VerificationResult(results=rows)


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
            claim_text = normalize_text(claim.text)
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
                excerpt = normalize_text(reference.excerpt)
                source = sources[reference.source_id - 1]
                source_text = normalize_text(str(source.get("text") or ""))
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
            # Invalid claims/references above are excluded from the package.
            # This flag describes the claims that can actually be displayed:
            # each survivor has at least one excerpt that passed the exact
            # normalized-substring check. Dropped-item details remain in
            # audit.validation_errors and lower the evidence strength.
            "exact_excerpts_passed": True,
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


def _apply_verification_results(
    package: dict,
    citations: List[dict],
    verifier_claims: List[dict],
    verification_rows: List[dict],
) -> Tuple[Optional[dict], List[dict], List[str], bool]:
    """Keep independently approved claims and remove rejected siblings.

    Verification remains fail-closed for malformed/incomplete verifier output
    and when no recommendation survives. A rejected optional supporting claim,
    however, must not erase a separately approved recommendation. Nothing that
    failed verification is ever displayed or cited.
    """
    expected_ids = {claim["claim_id"] for claim in verifier_claims}
    required_recommendation_ids = {
        claim["claim_id"] for claim in verifier_claims if claim["kind"] == "recommendation"
    }
    returned_ids = [row["claim_id"] for row in verification_rows]
    # Every displayed recommendation must be independently reviewed. Optional
    # supporting facts are never displayed when their audit row is missing,
    # rather than letting a provider omit one optional row and erase an
    # otherwise valid answer. Unknown/duplicate IDs are still malformed.
    well_formed = (
        len(returned_ids) == len(set(returned_ids))
        and set(returned_ids).issubset(expected_ids)
        and required_recommendation_ids.issubset(set(returned_ids))
    )
    if not well_formed:
        return None, [], [], True

    passed_ids = {
        row["claim_id"]
        for row in verification_rows
        if row["supported"]
        and row["relevant"]
        and row["safe"]
        and not row["overconfident"]
    }
    dropped_ids = sorted(expected_ids - passed_ids)
    recommendation_claims = [
        claim for claim in package["recommendation_claims"]
        if claim["claim_id"] in passed_ids
    ]
    if not recommendation_claims:
        return None, [], dropped_ids, False

    supporting_evidence = [
        claim for claim in package["supporting_evidence"]
        if claim["claim_id"] in passed_ids
    ]
    used_citation_ids = {
        citation_id
        for claim in recommendation_claims + supporting_evidence
        for citation_id in claim["citation_ids"]
    }
    filtered_citations = [
        citation for citation in citations if citation["id"] in used_citation_ids
    ]

    def render(claim: dict) -> str:
        markers = " ".join(f"[{citation_id}]" for citation_id in claim["citation_ids"])
        return f"{claim['text']} {markers}".strip()

    package["recommendation_claims"] = recommendation_claims
    package["supporting_evidence"] = supporting_evidence
    package["recommendation"] = "\n\n".join(render(claim) for claim in recommendation_claims)
    if dropped_ids:
        note = "Some generated statements did not pass independent evidence verification and were excluded."
        package["missing_evidence"] = f"{package.get('missing_evidence', '')} {note}".strip()
    return package, filtered_citations, dropped_ids, False


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
    role: str = "patient",
    pre_retrieved_sources: Optional[List[dict]] = None,
) -> GroundedAnswer:
    total_started = perf_counter()
    # The doctor experience can admit a broader near-domain retrieval band.
    # This affects admission only: exact excerpts, claim verification, and
    # safety checks below remain mandatory before an answer is displayed.
    retrieval_distance_gate = (
        DOCTOR_RETRIEVAL_DISTANCE_GATE if role == "doctor" else ABSURD_DISTANCE
    )
    retrieval_k = DOCTOR_RETRIEVAL_K if role == "doctor" else None
    if role == "doctor" and _clearly_non_medical_question(question):
        return _refusal(
            text=(
                "This assistant answers clinical questions only from the clinic's verified "
                "uploaded guidance. Please ask a medical guideline question."
            ),
            reason="non_medical_question",
            missing_evidence="The request is outside the clinical scope of the uploaded guidance.",
            audit={
                "retrieval_distance_gate": retrieval_distance_gate,
                "retrieval_k": retrieval_k,
                "latency_ms": {"total": round((perf_counter() - total_started) * 1000, 2)},
            },
        )
    # Role changes register and depth, not the prohibition on the model making
    # an individual diagnosis or prescribing decision. General guideline dose
    # questions are still allowed by personal_clinical_request().
    safety_reason = personal_clinical_request(question)
    if safety_reason:
        answer = (
            _doctor_personal_request_refusal(safety_reason)
            if role == "doctor"
            else _personal_request_refusal(safety_reason, mode)
        )
        answer.audit["retrieval_distance_gate"] = retrieval_distance_gate
        answer.audit["latency_ms"] = {"total": round((perf_counter() - total_started) * 1000, 2)}
        return answer

    retrieval_started = perf_counter()
    if pre_retrieved_sources is None:
        try:
            sources = retrieve(
                clinic_id,
                question,
                **({"k": retrieval_k} if retrieval_k is not None else {}),
                persist_dir=persist_dir,
                document_ids=document_ids,
                distance_gate=retrieval_distance_gate,
            )
        except RetrievalUnavailableError:
            return _refusal(
                text=DEPENDENCY_UNAVAILABLE_FALLBACK,
                reason="retrieval_unavailable",
                missing_evidence="The clinic knowledge index could not be accessed.",
                audit={
                    "retrieval_distance_gate": retrieval_distance_gate,
                    "retrieval_k": retrieval_k,
                    "latency_ms": {"total": round((perf_counter() - total_started) * 1000, 2)},
                },
            )
    else:
        # Internal staged evaluation passes the exact retrieval result forward
        # so generation cannot silently execute a second, different search.
        sources = list(pre_retrieved_sources)
    retrieval_ms = (perf_counter() - retrieval_started) * 1000

    if not sources:
        return _refusal(
            text=_insufficient_evidence_text(role, mode),
            reason="no_relevant_sources",
            missing_evidence="No verified clinic source directly addressing this question was retrieved.",
            audit={
                "retrieval_distance_gate": retrieval_distance_gate,
                "retrieval_k": retrieval_k,
                "latency_ms": {"retrieval": round(retrieval_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)},
            },
        )

    provider = get_provider()
    audit = {
        "provider": getattr(provider, "name", provider.__class__.__name__),
        "model": getattr(provider, "model", None),
        "prompt_version": PROMPT_VERSION,
        "retrieval_distance_gate": retrieval_distance_gate,
        "retrieval_k": retrieval_k,
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
    # A doctor has an independently verified extractive rescue below.  One
    # normal generation attempt gives the best clinician prose; avoiding a
    # second 45-second request prevents a formatting hiccup from becoming a
    # frontend timeout. Other roles retain the existing retry policy.
    generation_attempts = 1 if role == "doctor" else GENERATION_MAX_ATTEMPTS
    generation_failure: Optional[Exception] = None
    for attempt in range(generation_attempts):
        generation_started = perf_counter()
        try:
            result = provider.complete(
                system=get_system_prompt(role, mode),
                sources=sources,
                question=question,
                context=patient_context,
            )
        except Exception as exc:
            generation_failure = exc
            rate_limited = _is_rate_limit(exc)
            logger.warning(
                "generation failed (%s): %s: %s",
                "rate_limited" if rate_limited else "unavailable",
                type(exc).__name__,
                exc,
            )
            if role != "doctor":
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
            break
        generation_ms += (perf_counter() - generation_started) * 1000

        if not result.sufficient:
            return _refusal(
                text=_insufficient_evidence_text(role, mode),
                reason="model_reported_insufficient_context",
                sources=sources,
                missing_evidence=result.missing_evidence,
                audit={**audit, "latency_ms": {"retrieval": round(retrieval_ms, 2), "generation": round(generation_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
            )

        package, citations, verifier_claims, validation_errors = validate_claims(result, sources)
        if package is not None or attempt == generation_attempts - 1:
            break

    # A strict LLM can occasionally fail to produce valid JSON or reproduce an
    # exact excerpt even when the retrieved guideline plainly contains one.
    # For a doctor, preserve that potentially useful, *quoted* evidence path;
    # it still goes through validate_claims and the independent semantic
    # verifier below. It cannot turn an unrelated source into an answer.
    if package is None and role == "doctor":
        result = _doctor_extractive_rescue(sources, question)
        package, citations, verifier_claims, validation_errors = validate_claims(result, sources)
        audit["generation_rescue"] = {
            "used": package is not None,
            "reason": "generation_exception" if generation_failure else "invalid_generated_claims",
        }

    audit["validation_errors"] = validation_errors
    # package is None only when every recommendation claim independently
    # failed validation on every attempt — a claim-level error with
    # surviving siblings already produced a package above and proceeds to
    # verification below, rather than discarding claims that passed their
    # own exact-quote check.
    if package is None:
        logger.info("claim validation failed after %d attempts: %s", GENERATION_MAX_ATTEMPTS, validation_errors)
        return _refusal(
            text=_insufficient_evidence_text(role, mode),
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
        # If the provider was unavailable before it could generate an answer,
        # the doctor-only rescue above is an exact source quotation rather than
        # a model assertion.  Verify that constrained shape and its reranker
        # relevance locally so an outage does not hide clearly supported
        # uploaded guidance. Any normal generated claim still fails closed.
        if role == "doctor" and audit.get("generation_rescue", {}).get("used"):
            verification = _local_extractive_verification(verifier_claims, citations)
            audit["verification_mode"] = "local_extractive_fallback"
        else:
            return _refusal(
                text=RATE_LIMITED_FALLBACK if rate_limited else DEPENDENCY_UNAVAILABLE_FALLBACK,
                reason="evidence_verification_rate_limited" if rate_limited else "evidence_verification_unavailable",
                sources=sources,
                missing_evidence="The retrieved evidence could not be independently verified.",
                audit={**audit, "latency_ms": {"retrieval": round(retrieval_ms, 2), "generation": round(generation_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
            )
    verification_ms = (perf_counter() - verification_started) * 1000
    _failed, verification_rows = verification_failure(
        verification, {claim["claim_id"] for claim in verifier_claims}
    )
    audit["verification"] = verification_rows
    rejected_recommendation = any(
        row["claim_id"].startswith("recommendation-")
        and not (
            row["supported"]
            and row["relevant"]
            and row["safe"]
            and not row["overconfident"]
        )
        for row in verification_rows
    )
    if role == "doctor" and rejected_recommendation:
        # A model can combine a guideline-specific answer with a generic one.
        # Once the auditor rejects any recommendation claim, do not show the
        # remaining generic sibling as though it answered the question. Fall
        # back to a single, high-relevance exact source quote instead.
        rescue_result = _doctor_extractive_rescue(sources, question)
        rescue_package, rescue_citations, rescue_claims, rescue_errors = validate_claims(
            rescue_result, sources
        )
        if rescue_package is not None:
            rescue_verification = _local_extractive_verification(
                rescue_claims, rescue_citations
            )
            rescue_rows = [
                {
                    "claim_id": row.claim_id,
                    "supported": row.supported,
                    "relevant": row.relevant,
                    "safe": row.safe,
                    "overconfident": row.overconfident,
                    "reason": row.reason,
                }
                for row in rescue_verification.results
            ]
            package, citations, dropped_verifier_claims, malformed_verification = (
                _apply_verification_results(
                    rescue_package,
                    rescue_citations,
                    rescue_claims,
                    rescue_rows,
                )
            )
            verifier_claims = rescue_claims
            validation_errors = rescue_errors
            verification_rows = rescue_rows
            audit["verification"] = verification_rows
            audit["verification_mode"] = "local_extractive_after_rejected_recommendation"
            audit["generation_rescue"] = {
                "used": package is not None,
                "reason": "rejected_generated_recommendation",
            }
        else:
            package = None
            citations = []
            dropped_verifier_claims = []
            malformed_verification = True
    else:
        package, citations, dropped_verifier_claims, malformed_verification = (
            _apply_verification_results(
                package,
                citations,
                verifier_claims,
                verification_rows,
            )
        )
    audit["dropped_verifier_claims"] = dropped_verifier_claims
    if package is None:
        missing = (
            "The evidence verifier returned an incomplete or malformed claim audit."
            if malformed_verification
            else "No generated recommendation claim passed independent evidence verification."
        )
        return _refusal(
            text=_insufficient_evidence_text(role, mode),
            reason="evidence_verification_failed",
            sources=sources,
            missing_evidence=missing,
            audit={**audit, "latency_ms": {"retrieval": round(retrieval_ms, 2), "generation": round(generation_ms, 2), "verification": round(verification_ms, 2), "total": round((perf_counter() - total_started) * 1000, 2)}},
        )

    package["checks"].update(
        {"evidence_match_passed": True, "safety_passed": True, "verifier_passed": True}
    )
    package["evidence_strength"] = _strength(
        package,
        citations,
        result.partial or bool(validation_errors) or bool(dropped_verifier_claims),
    )
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
