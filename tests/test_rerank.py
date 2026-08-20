from langchain_core.documents import Document

from rag.rerank import rerank_hits


class FakeCrossEncoder:
    def predict(self, pairs, show_progress_bar=False):
        assert show_progress_bar is False
        return [0.1 if "generic" in text else 0.9 for _, text in pairs]


def test_reranker_reorders_candidates_and_preserves_vector_distance():
    generic = Document(page_content="generic diabetes information")
    specific = Document(page_content="specific metformin contraindication")

    ranked = rerank_hits(
        "When is metformin contraindicated?",
        [(generic, 0.2), (specific, 0.6)],
        k=2,
        model=FakeCrossEncoder(),
    )

    assert ranked[0] == (specific, 0.6, 0.9)
    assert ranked[1] == (generic, 0.2, 0.1)


def test_reranker_honours_k():
    docs = [(Document(page_content=f"specific {i}"), i / 10) for i in range(3)]
    assert len(rerank_hits("question", docs, k=1, model=FakeCrossEncoder())) == 1


def test_reranker_handles_empty_candidates_without_loading_model():
    assert rerank_hits("question", [], k=5) == []
