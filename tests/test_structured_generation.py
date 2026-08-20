from app.llm import (
    ClaimVerification,
    EvidenceReference,
    GeneratedClaim,
    LLMResult,
    VerificationResult,
)
from app.services import generation
from app.services.safety import personal_clinical_request
from app.routers.chat import _insert_assistant_message
from rag.config import ABSURD_DISTANCE, DOCTOR_RETRIEVAL_DISTANCE_GATE, DOCTOR_RETRIEVAL_K


def _source(index=1, text="Offer structured education and regular review."):
    return {
        "rank": index,
        "text": text,
        "title": f"Trusted guideline {index}",
        "source": f"guide-{index}.pdf",
        "document_id": f"doc-{index}",
        "publisher": "Trusted publisher",
        "source_url": "https://example.org/guideline",
        "page_number": index + 4,
        "section_title": "Care",
        "chunk_id": f"chunk-{index}",
        "distance": 0.4 + index / 100,
        "rerank_score": 7.0 - index,
    }


class PassingProvider:
    name = "test"
    model = "test-model"

    def __init__(self, result):
        self.result = result

    def complete(self, **_kwargs):
        return self.result

    def verify(self, question, claims):
        return VerificationResult(
            [
                ClaimVerification(
                    claim_id=claim["claim_id"],
                    supported=True,
                    relevant=True,
                    safe=True,
                    overconfident=False,
                )
                for claim in claims
            ]
        )


def _result(refs=None, *, partial=False):
    refs = refs or [EvidenceReference(1, "structured education and regular review")]
    return LLMResult(
        recommendation_claims=[GeneratedClaim("Offer structured education and regular review.", refs)],
        supporting_claims=[GeneratedClaim("Regular review is included in the guidance.", refs)],
        sufficient=True,
        partial=partial,
        missing_evidence="The source does not cover individual scheduling." if partial else "",
    )


def _wire(monkeypatch, provider, sources=None):
    monkeypatch.setattr(generation, "retrieve", lambda *_args, **_kwargs: sources or [_source()])
    monkeypatch.setattr(generation, "get_provider", lambda: provider)


def test_structured_answer_contains_exact_auditable_citation(monkeypatch):
    _wire(monkeypatch, PassingProvider(_result()))
    answer = generation.answer_question("clinic", "What does the guidance recommend?")

    assert answer.grounded is True
    assert answer.evidence_strength == "medium"
    assert answer.evidence["checks"]["citation_coverage"] == 1.0
    assert answer.evidence["checks"]["verifier_passed"] is True
    assert answer.citations[0]["id"] == "C1"
    assert answer.citations[0]["chunk_id"] == "chunk-1"
    assert answer.citations[0]["source_url"] == "https://example.org/guideline"
    assert answer.citations[0]["excerpt"] == "structured education and regular review"


def test_duplicate_evidence_is_deduplicated(monkeypatch):
    refs = [
        EvidenceReference(1, "structured education and regular review"),
        EvidenceReference(1, "structured education and regular review"),
    ]
    _wire(monkeypatch, PassingProvider(_result(refs)))
    answer = generation.answer_question("clinic", "What does the guidance recommend?")
    assert answer.grounded is True
    assert len(answer.citations) == 1


def test_invented_excerpt_fails_closed(monkeypatch):
    result = _result([EvidenceReference(1, "words that are not in the source")])
    _wire(monkeypatch, PassingProvider(result))
    answer = generation.answer_question("clinic", "What does the guidance recommend?")
    assert answer.grounded is False
    assert answer.reason == "evidence_validation_failed"
    assert answer.evidence_strength == "insufficient"


def test_doctor_insufficient_evidence_copy_is_clinician_facing():
    text = generation._insufficient_evidence_text("doctor", "general")

    assert "professional judgment" in text
    assert "speak to your doctor" not in text


def test_doctor_uses_a_wider_retrieval_gate_without_changing_the_default(monkeypatch):
    captured = []

    def retrieve(*_args, **kwargs):
        captured.append((kwargs["distance_gate"], kwargs.get("k")))
        return [_source()]

    monkeypatch.setattr(generation, "retrieve", retrieve)
    monkeypatch.setattr(generation, "get_provider", lambda: PassingProvider(_result()))

    doctor = generation.answer_question("clinic", "What does the guidance recommend?", role="doctor")
    standard = generation.answer_question("clinic", "What does the guidance recommend?")

    assert doctor.grounded is True
    assert standard.grounded is True
    assert captured == [(DOCTOR_RETRIEVAL_DISTANCE_GATE, DOCTOR_RETRIEVAL_K), (ABSURD_DISTANCE, None)]
    assert doctor.audit["retrieval_distance_gate"] == DOCTOR_RETRIEVAL_DISTANCE_GATE
    assert standard.audit["retrieval_distance_gate"] == ABSURD_DISTANCE
    assert doctor.audit["retrieval_k"] == DOCTOR_RETRIEVAL_K


def test_doctor_uses_verified_extractive_rescue_after_invalid_model_claim(monkeypatch):
    invalid = LLMResult(
        recommendation_claims=[GeneratedClaim("Unsupported wording", [EvidenceReference(1, "not in source")])],
        sufficient=True,
    )
    _wire(monkeypatch, PassingProvider(invalid), [_source(text="Offer structured education and regular review.")])

    answer = generation.answer_question("clinic", "What support should be offered?", role="doctor")

    assert answer.grounded is True
    assert answer.text == "The verified guideline states: Offer structured education and regular review. [C1]"
    assert answer.citations[0]["excerpt"] == "Offer structured education and regular review."
    assert answer.audit["generation_rescue"]["used"] is True


def test_doctor_extractive_rescue_still_refuses_when_verifier_rejects_it(monkeypatch):
    invalid = LLMResult(
        recommendation_claims=[GeneratedClaim("Unsupported wording", [EvidenceReference(1, "not in source")])],
        sufficient=True,
    )
    provider = PassingProvider(invalid)
    provider.verify = lambda question, claims: VerificationResult([
        ClaimVerification(claim["claim_id"], False, False, True, False, "Not relevant to the question")
        for claim in claims
    ])
    _wire(monkeypatch, provider, [_source(text="Offer structured education and regular review.")])

    answer = generation.answer_question("clinic", "How do I repair my car?", role="doctor")

    assert answer.grounded is False
    assert answer.reason == "non_medical_question"


def test_doctor_provider_outage_can_return_strong_exact_source_quote(monkeypatch):
    class UnavailableProvider:
        name = "unavailable"
        model = "test"

        def complete(self, **_kwargs):
            raise ConnectionError("provider unavailable")

        def verify(self, **_kwargs):
            raise ConnectionError("provider unavailable")

    source = _source(text="For adults under 80, reduce clinic blood pressure to below 140/90 mmHg.")
    source["rerank_score"] = 6.5
    _wire(monkeypatch, UnavailableProvider(), [source])

    answer = generation.answer_question(
        "clinic", "What blood pressure target is recommended for adults under 80?", role="doctor"
    )

    assert answer.grounded is True
    assert answer.evidence_strength == "medium"
    assert answer.audit["verification_mode"] == "local_extractive_fallback"
    assert "below 140/90 mmHg" in answer.text


def test_doctor_provider_outage_does_not_show_irrelevant_quote(monkeypatch):
    class UnavailableProvider:
        name = "unavailable"
        model = "test"

        def complete(self, **_kwargs):
            raise ConnectionError("provider unavailable")

        def verify(self, **_kwargs):
            raise ConnectionError("provider unavailable")

    source = _source(text="Offer structured education and regular review.")
    source["rerank_score"] = -4.0
    _wire(monkeypatch, UnavailableProvider(), [source])

    answer = generation.answer_question("clinic", "How do I change a car oil filter?", role="doctor")

    assert answer.grounded is False
    assert answer.reason == "non_medical_question"


def test_extractive_rescue_prefers_initial_treatment_over_escalation_when_question_is_initial():
    escalation = _source(
        1,
        "For adults with type 2 diabetes and no relevant comorbidity who need further medicines, offer a DPP-4 inhibitor.",
    )
    escalation["rerank_score"] = 5.9
    initial = _source(
        2,
        "For adults with type 2 diabetes and no relevant comorbidity, offer modified-release metformin and an SGLT-2 inhibitor.",
    )
    initial["rerank_score"] = 5.6

    result = generation._doctor_extractive_rescue(
        [escalation, initial],
        "What is the first-line treatment for adults with type 2 diabetes and no relevant comorbidity?",
    )

    assert result.recommendation_claims[0].evidence[0].source_id == 2


def test_extractive_rescue_keeps_a_high_ranked_table_like_source_without_sentence_punctuation():
    ordinary = _source(1, "Offer structured education and regular review.")
    ordinary["rerank_score"] = 4.0
    table = _source(2, "Diagnostic criteria for diabetes HbA1c 48 mmol/mol fasting plasma glucose 7.0 mmol/L")
    table["rerank_score"] = 7.0

    result = generation._doctor_extractive_rescue(
        [ordinary, table], "What are the diagnostic criteria for diabetes?"
    )

    assert result.recommendation_claims[0].evidence[0].source_id == 2


def test_invalid_optional_claim_is_dropped_without_tainting_displayed_exact_excerpt(monkeypatch):
    result = _result()
    result.supporting_claims = [
        GeneratedClaim(
            "This optional statement cannot be cited.",
            [EvidenceReference(1, "words that are not in the source")],
        )
    ]
    _wire(monkeypatch, PassingProvider(result))

    answer = generation.answer_question("clinic", "What does the guidance recommend?")

    assert answer.grounded is True
    assert answer.evidence["recommendation_claims"]
    assert answer.evidence["supporting_evidence"] == []
    assert answer.evidence["checks"]["exact_excerpts_passed"] is True
    assert answer.evidence_strength == "low"
    assert any("invented_or_invalid_excerpt" in error for error in answer.audit["validation_errors"])


def test_uncited_claim_fails_closed(monkeypatch):
    result = _result()
    result.recommendation_claims[0] = GeneratedClaim("An uncited claim.", [])
    _wire(monkeypatch, PassingProvider(result))
    answer = generation.answer_question("clinic", "What does the guidance recommend?")
    assert answer.grounded is False
    assert answer.reason == "evidence_validation_failed"


def test_verifier_rejection_fails_closed(monkeypatch):
    provider = PassingProvider(_result())

    def reject(question, claims):
        return VerificationResult(
            [ClaimVerification(claim["claim_id"], False, True, True, False, "Not entailed") for claim in claims]
        )

    provider.verify = reject
    _wire(monkeypatch, provider)
    answer = generation.answer_question("clinic", "What does the guidance recommend?")
    assert answer.grounded is False
    assert answer.reason == "evidence_verification_failed"


def test_rejected_optional_supporting_claim_is_dropped(monkeypatch):
    provider = PassingProvider(_result())

    def reject_supporting(question, claims):
        return VerificationResult(
            [
                ClaimVerification(
                    claim["claim_id"],
                    supported=claim["kind"] == "recommendation",
                    relevant=True,
                    safe=True,
                    overconfident=False,
                    reason="Optional detail was not directly entailed"
                    if claim["kind"] == "supporting"
                    else "Recommendation is directly supported",
                )
                for claim in claims
            ]
        )

    provider.verify = reject_supporting
    _wire(monkeypatch, provider)
    answer = generation.answer_question("clinic", "What does the guidance recommend?")

    assert answer.grounded is True
    assert answer.evidence_strength == "low"
    assert answer.evidence["checks"]["verifier_passed"] is True
    assert answer.evidence["supporting_evidence"] == []
    assert answer.evidence["recommendation_claims"]
    assert answer.audit["dropped_verifier_claims"] == ["supporting-1"]


def test_missing_optional_verifier_row_drops_optional_fact_but_keeps_verified_recommendation(monkeypatch):
    provider = PassingProvider(_result())
    provider.verify = lambda question, claims: VerificationResult(
        [ClaimVerification("recommendation-1", True, True, True, False)]
    )
    _wire(monkeypatch, provider)

    answer = generation.answer_question("clinic", "What does the guidance recommend?")

    assert answer.grounded is True
    assert answer.evidence["supporting_evidence"] == []
    assert answer.audit["dropped_verifier_claims"] == ["supporting-1"]


def test_missing_recommendation_verifier_row_still_fails_closed(monkeypatch):
    provider = PassingProvider(_result())
    provider.verify = lambda question, claims: VerificationResult(
        [ClaimVerification("supporting-1", True, True, True, False)]
    )
    _wire(monkeypatch, provider)

    answer = generation.answer_question("clinic", "What does the guidance recommend?")

    assert answer.grounded is False
    assert answer.reason == "evidence_verification_failed"
    assert "incomplete or malformed" in answer.evidence["missing_evidence"]


def test_verifier_outage_fails_closed(monkeypatch):
    provider = PassingProvider(_result())
    provider.verify = lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout"))
    _wire(monkeypatch, provider)
    answer = generation.answer_question("clinic", "What does the guidance recommend?")
    assert answer.grounded is False
    assert answer.reason == "evidence_verification_unavailable"
    assert "can't access" in answer.text


def test_evidence_strength_high_and_low(monkeypatch):
    sources = [_source(1), _source(2, "Offer structured education and regular review.")]
    refs = [
        EvidenceReference(1, "structured education and regular review"),
        EvidenceReference(2, "structured education and regular review"),
    ]
    _wire(monkeypatch, PassingProvider(_result(refs)), sources)
    assert generation.answer_question("clinic", "What is recommended?").evidence_strength == "high"

    _wire(monkeypatch, PassingProvider(_result(partial=True)), [_source()])
    assert generation.answer_question("clinic", "What is recommended?").evidence_strength == "low"


def test_personal_diagnosis_and_dosage_are_refused_before_retrieval(monkeypatch):
    monkeypatch.setattr(
        generation,
        "retrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retrieval must not run")),
    )
    for question in (
        "Do I have diabetes?",
        "How much of my medicine should I take?",
        "What dose should I prescribe for my patient?",
    ):
        answer = generation.answer_question("clinic", question)
        assert answer.grounded is False
        assert answer.reason.startswith("patient_specific_")
        assert answer.evidence_strength == "insufficient"

    assert personal_clinical_request("What dosage does the guideline describe in general?") is None
    assert personal_clinical_request("When should someone newly diagnosed be referred?") is None


def test_doctor_role_changes_register_but_not_patient_specific_safety(monkeypatch):
    monkeypatch.setattr(
        generation,
        "retrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe individual request must be refused before retrieval")
        ),
    )
    refused = generation.answer_question(
        "clinic",
        "What dose should I prescribe for my patient?",
        role="doctor",
    )
    assert refused.grounded is False
    assert refused.reason == "patient_specific_dosage_or_treatment"
    assert "general guideline question" in refused.text

    _wire(monkeypatch, PassingProvider(_result()))
    general = generation.answer_question(
        "clinic",
        "What dosage does the guideline describe in general?",
        role="doctor",
    )
    assert general.grounded is True


def test_generation_can_use_the_exact_pre_retrieved_stage_output(monkeypatch):
    sources = [_source()]
    monkeypatch.setattr(
        generation,
        "retrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generation must not run a second retrieval")
        ),
    )
    monkeypatch.setattr(
        generation,
        "get_provider",
        lambda: PassingProvider(_result()),
    )

    answer = generation.answer_question(
        "clinic",
        "What does the guidance recommend?",
        role="doctor",
        pre_retrieved_sources=sources,
    )

    assert answer.grounded is True
    assert answer.citations[0]["chunk_id"] == sources[0]["chunk_id"]


def test_malformed_llm_json_is_insufficient():
    assert LLMResult.from_json("not json").sufficient is False
    assert LLMResult.from_json('{"sufficient": true, "recommendation_claims": []}').sufficient is False


def test_message_persistence_falls_back_before_additive_migration():
    attempts = []

    class Query:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            attempts.append(self.payload)
            if "evidence" in self.payload:
                raise RuntimeError("Could not find the 'evidence' column in the schema cache")
            return type("Response", (), {"data": [{"id": "message-1", "created_at": "2026-01-01T00:00:00Z", **self.payload}]})()

    class Table:
        def insert(self, payload):
            return Query(payload)

    class DB:
        def table(self, name):
            assert name == "messages"
            return Table()

    user = type("User", (), {"clinic_id": "clinic-1", "db": DB()})()
    answer = generation.GroundedAnswer(
        "Grounded text [C1]",
        citations=[{"document": "Guide", "page": 1, "section": "Care"}],
        grounded=True,
        evidence={"evidence_strength": "medium"},
        audit={"prompt_version": "test"},
    )

    row = _insert_assistant_message(user, "session-1", answer)

    assert len(attempts) == 2
    assert row["evidence"] == {"evidence_strength": "medium"}
    assert row["grounded"] is True
