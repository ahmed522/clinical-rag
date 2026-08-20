from types import SimpleNamespace
import sys

from app.services import retrieval
from rag.config import ABSURD_DISTANCE, DOCTOR_RETRIEVAL_DISTANCE_GATE


class _Document:
    page_content = "Relevant passage"
    metadata = {"source": "guideline.pdf", "chunk_id": "chunk-1"}


def _retrieve_at_distance(monkeypatch, distance, gate=ABSURD_DISTANCE):
    class FakeChroma:
        def __init__(self, **_kwargs):
            pass

        def similarity_search_with_score(self, *_args, **_kwargs):
            return [(_Document(), distance)]

    monkeypatch.setitem(sys.modules, "langchain_chroma", SimpleNamespace(Chroma=FakeChroma))
    monkeypatch.setattr(retrieval, "_get_embeddings", lambda: object())
    monkeypatch.setattr(retrieval, "RERANK_ENABLED", False)
    return retrieval.retrieve("clinic", "near-domain question", distance_gate=gate)


def test_default_distance_gate_remains_165_and_doctor_gate_admits_middle_distance(monkeypatch):
    # A candidate between the two gates stays out for standard callers but
    # reaches the post-retrieval pipeline for the doctor-specific caller.
    assert _retrieve_at_distance(monkeypatch, 1.70) == []
    admitted = _retrieve_at_distance(monkeypatch, 1.70, DOCTOR_RETRIEVAL_DISTANCE_GATE)

    assert ABSURD_DISTANCE == 1.65
    assert DOCTOR_RETRIEVAL_DISTANCE_GATE == 1.80
    assert admitted[0]["distance"] == 1.7


def test_doctor_gate_still_refuses_out_of_range_question(monkeypatch):
    assert _retrieve_at_distance(monkeypatch, 1.81, DOCTOR_RETRIEVAL_DISTANCE_GATE) == []
