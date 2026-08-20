"""
Hybrid dense + lexical retrieval, fused with reranking via Reciprocal Rank
Fusion (RRF).

Why this exists (see rag/config.py's RRF_K comment for the full measurement):
on the labelled evaluation set, the cross-encoder reranker alone sometimes
actively inverts a good vector rank (position 6 pushed to ~24), and the
dense embedding alone sometimes misses chunks that share exact clinical
terms with the question ("DKA and HHS") but aren't semantically close by
this embedding model. Fusing vector rank, BM25 rank, and reranker rank
gives every signal a vote instead of trusting any single one in isolation.

Shared by app/services/retrieval.py (production) and the offline evaluators
in scripts/, the same way rag/rerank.py's rerank_hits already is — so
production and evaluation never measure two different retrieval paths.
"""

import re
from typing import Optional, Sequence

from langchain_core.documents import Document

from rag import config as rag_config
from rag.rerank import rerank_hits


def _tokenize(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


def _chunk_key(document: Document) -> str:
    chunk_id = document.metadata.get("chunk_id")
    if chunk_id:
        return chunk_id
    # Defensive fallback; chunk_id should always be set by rag/chunk.py.
    return f"{document.metadata.get('source')}:{document.metadata.get('page_number')}:{document.page_content[:50]}"


def reciprocal_rank_fusion(*ranked_id_lists: Sequence[str], k: Optional[int] = None) -> dict:
    """score(id) = sum(1 / (k + rank)) across every list the id appears in, 1-based rank."""
    if k is None:
        k = rag_config.RRF_K
    scores: dict = {}
    for ranked_ids in ranked_id_lists:
        for rank, item_id in enumerate(ranked_ids, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_retrieve(
    store,
    question: str,
    candidate_k: int,
    k: int,
    where: Optional[dict] = None,
) -> list:
    """
    Vector search + BM25 over the same (optionally filtered) corpus, fused
    via RRF into a candidate pool, then cross-encoder reranked, then fused
    again with the pre-rerank rank for the final order.

    `where` MUST be the identical filter the caller would otherwise pass to
    similarity_search_with_score — this is guardrail #5 territory. An
    unverified or excluded document must never enter the BM25 channel
    either, so the corpus fetch below uses the same filter.

    Returns [(Document, vector_distance_or_None, rerank_score), ...] — the
    same shape rag.rerank.rerank_hits already returns, so existing callers'
    unpacking doesn't change.
    """
    vector_hits = store.similarity_search_with_score(question, k=candidate_k, filter=where)
    vector_by_key = {_chunk_key(doc): (doc, float(distance)) for doc, distance in vector_hits}
    vector_rank_ids = list(vector_by_key.keys())

    corpus = store.get(where=where, include=["documents", "metadatas"])
    bm25_documents = [
        Document(page_content=text, metadata=metadata or {})
        for text, metadata in zip(corpus["documents"], corpus["metadatas"])
    ]

    bm25_rank_ids: list = []
    bm25_by_key: dict = {}
    if bm25_documents:
        from rank_bm25 import BM25Okapi

        tokenized_corpus = [_tokenize(doc.page_content) for doc in bm25_documents]
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(_tokenize(question))
        ranked_indices = sorted(range(len(bm25_documents)), key=lambda i: scores[i], reverse=True)
        for index in ranked_indices[:candidate_k]:
            doc = bm25_documents[index]
            key = _chunk_key(doc)
            bm25_rank_ids.append(key)
            bm25_by_key.setdefault(key, doc)

    fused_scores = reciprocal_rank_fusion(vector_rank_ids, bm25_rank_ids)
    if not fused_scores:
        return []

    fused_order = sorted(fused_scores, key=lambda key: fused_scores[key], reverse=True)[:candidate_k]

    candidate_hits = []
    for key in fused_order:
        if key in vector_by_key:
            doc, distance = vector_by_key[key]
        else:
            doc, distance = bm25_by_key[key], None
        candidate_hits.append((doc, distance))

    if not candidate_hits:
        return []

    # Rerank the FULL candidate pool (not yet truncated to k) so a chunk the
    # cross-encoder demotes still has a fair pre-rerank rank to fall back on
    # in the fusion below, rather than being dropped before it gets a vote.
    reranked_full = rerank_hits(question, candidate_hits, k=len(candidate_hits))
    if not reranked_full:
        return []

    rerank_rank_ids = [_chunk_key(doc) for doc, _, _ in reranked_full]
    final_scores = reciprocal_rank_fusion(fused_order, rerank_rank_ids)
    final_order = sorted(final_scores, key=lambda key: final_scores[key], reverse=True)[:k]

    reranked_by_key = {_chunk_key(doc): (doc, distance, score) for doc, distance, score in reranked_full}
    return [reranked_by_key[key] for key in final_order if key in reranked_by_key]
