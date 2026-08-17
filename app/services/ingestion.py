"""
Runs an uploaded PDF through the existing pipeline, scoped to one clinic.

Deliberately a thin wrapper: the extraction, furniture removal, chunking
and embedding logic all stay in src/ where they are already measured and
regression-tested. This module only supplies the tenant and the document
identity, then records provenance in the database.

Stage order matters and is easy to get wrong:

    ingest -> preprocessing -> chunk -> embed

preprocessing sits in the middle and is not optional. It strips repeated
page furniture (running titles, copyright footers, page numbers) by
frequency. Skipping it puts that furniture into a quarter of all chunks,
where it dilutes every embedding.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chunk import chunk_document  # noqa: E402
from config import collection_name_for  # noqa: E402
from embed import index_chunks  # noqa: E402
from ingest import extract_pdf  # noqa: E402
from preprocessing import process_document  # noqa: E402

from app.models import Chunk  # noqa: E402


def ingest_document(db, document, persist_dir=None):
    """
    Extract, clean, chunk, embed and record one uploaded document.

    Returns (page_count, chunk_count).

    Every chunk is written to the clinic's OWN Chroma collection, so a
    patient's retrieval can only ever reach their clinic's documents.
    """
    from config import CHROMA_DIR

    persist_dir = str(persist_dir or CHROMA_DIR)

    metadata = {
        "title": document.title,
        "publisher": document.publisher,
        "url": document.source_url,
        "topic": document.topic,
    }

    extracted = extract_pdf(document.file_path, metadata=metadata)

    # Furniture removal + page-type labelling. process_document returns
    # (document, removed_counter, dropped_pages); only the first is needed
    # here, the rest is reporting for the CLI.
    preprocessed, _removed, _dropped = process_document(extracted)

    chunks = chunk_document(preprocessed, document_id=document.id)

    # Provenance rows first: the database is the source of truth for
    # where a chunk came from, and vector_ref is the join key back to the
    # embedding. Deterministic chunk ids keep that link stable across
    # re-ingests.
    for chunk in chunks:
        db.add(
            Chunk(
                document_id=document.id,
                clinic_id=document.clinic_id,
                content=chunk["text"],
                section_title=chunk.get("section_title"),
                page_number=chunk.get("page_number"),
                vector_ref=chunk["chunk_id"],
            )
        )

    index_chunks(
        chunks,
        collection_name=collection_name_for(document.clinic_id),
        persist_dir=persist_dir,
    )

    return extracted.get("total_pages", 0), len(chunks)
