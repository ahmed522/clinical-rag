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
