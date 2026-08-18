"""
Per-clinic retrieval with the loose relevance gate.

Two things happen here, and only one of them is a safety mechanism:

1. Tenant scoping — search runs against clinic_{id}'s own Chroma
   collection, so another clinic's documents are not merely filtered out,
   they are never searched.

2. A LOOSE distance gate — rejects questions that are clearly outside the
   corpus entirely, before any LLM call.

The gate is deliberately permissive, and this is measured rather than
guessed. On the 38-query labelled evaluation set the in-scope and
out-of-scope score ranges OVERLAP: the worst real clinical question
scores 0.833 while the closest out-of-scope question scores 0.755. So no
threshold can separate them. A cut-off tight enough to reject every
out-of-scope question also refuses real ones — including "when should a
patient be referred urgently?", which is exactly the question that must
never be refused.

The gate therefore only catches the obviously absurd (measured 0.97-1.84).
Near-domain questions — type 1 diabetes in a diabetes clinic, pregnancy,
"what dose should I take" — pass the gate by design and are refused by the
LLM's grounding judgment instead, because deciding them needs the text,
not a number.
"""

import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import (  # noqa: E402
    ABSURD_DISTANCE,
    CHROMA_DIR,
    EMBEDDING_MODEL,
    RETRIEVAL_K,
    collection_name_for,
)

_embeddings = None


def _get_embeddings():
    """Load the embedding model once per process; it is slow to construct."""
    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings

        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return _embeddings


def retrieve(
    clinic_id: str,
    question: str,
    k: int = RETRIEVAL_K,
    persist_dir=None,
    document_ids: Optional[List[str]] = None,
) -> List[dict]:
    """
    Return up to k chunks from this clinic's collection, or [] if the
    question is clearly outside the corpus.

    k defaults to 8 because that is where recall plateaus on the labelled
    set (47% at k=1, 68% at k=4, 84% at k=8, no gain at k=10).

    document_ids restricts the search to specific documents. Patient-facing
    callers pass the clinic's VERIFIED documents, which is how guardrail #5
    is enforced: an uploaded guideline the clinic has not yet confirmed is
    official cannot reach a patient's answer.

    Note the empty-list case is not the same as None. None means "no
    document restriction" (the clinic-facing/CLI path). An empty list means
    "no documents are eligible" and must return nothing — falling through to
    an unfiltered search there would answer from precisely the documents the
    caller just excluded.
    """
    from langchain_chroma import Chroma

    if document_ids is not None and not document_ids:
        return []

    store = Chroma(
        collection_name=collection_name_for(clinic_id),
        embedding_function=_get_embeddings(),
        persist_directory=str(persist_dir or CHROMA_DIR),
    )

    search_filter = None
    if document_ids:
        # Chroma rejects $in with a single-element list on some versions;
        # an equality filter is the same query and is universally accepted.
        search_filter = (
            {"document_id": document_ids[0]}
            if len(document_ids) == 1
            else {"document_id": {"$in": list(document_ids)}}
        )

    try:
        hits = store.similarity_search_with_score(question, k=k, filter=search_filter)
    except Exception:
        # A clinic with no documents yet has no collection. That is not an
        # error — it is simply nothing to ground an answer in.
        return []

    if not hits:
        return []

    # Chroma returns distance: lower is closer.
    if hits[0][1] > ABSURD_DISTANCE:
        return []

    return [
        {
            "text": doc.page_content,
            "title": doc.metadata.get("title") or doc.metadata.get("source", "Unknown document"),
            "source": doc.metadata.get("source"),
            "page_number": doc.metadata.get("page_number"),
            "section_title": doc.metadata.get("section_title"),
            "chunk_id": doc.metadata.get("chunk_id"),
            "distance": round(float(score), 4),
        }
        for doc, score in hits
    ]
