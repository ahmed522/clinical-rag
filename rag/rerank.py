"""Cross-encoder reranking shared by the API, CLI, and evaluation scripts."""

from functools import lru_cache
from typing import Sequence

from rag.config import HF_LOCAL_FILES_ONLY, RERANK_MODEL


@lru_cache(maxsize=1)
def get_reranker():
    """Load the cross-encoder once per process."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANK_MODEL, local_files_only=HF_LOCAL_FILES_ONLY)


def rerank_hits(question: str, hits: Sequence[tuple], k: int, model=None) -> list[tuple]:
    """Return ``hits`` ordered by descending cross-encoder relevance.

    Each input hit is ``(Document, vector_distance)``.  The vector distance is
    retained for safety gating and diagnostics; the cross-encoder score is
    appended as a third item.  ``vector_distance`` may be ``None`` (a
    lexical-only candidate with no vector distance, e.g. from BM25 fusion) and
    is passed through unchanged — it is never used in the reranking score
    itself.  Supplying ``model`` keeps this function cheap to unit test
    without downloading a model.
    """
    if k <= 0 or not hits:
        return []

    scorer = model or get_reranker()
    pairs = [(question, document.page_content) for document, _ in hits]
    scores = scorer.predict(pairs, show_progress_bar=False)

    ranked = [
        (document, float(distance) if distance is not None else None, float(score))
        for (document, distance), score in zip(hits, scores)
    ]
    ranked.sort(key=lambda item: item[2], reverse=True)
    return ranked[:k]
