"""
Guideline upload and verification (clinic admin only).

Provenance lives in two places by design, mirrored: Supabase Postgres
holds the `documents`/`chunks` rows (source of truth for what a citation
points at), and the local Chroma index holds the embeddings. `vector_ref`
is the join key between them, and it is the deterministic chunk id from
src/chunk.py — not a fresh uuid — so re-ingesting a document overwrites
its own vectors instead of orphaning rows on either side.

The raw PDF itself goes to the `guidelines` Supabase Storage bucket, keyed
{clinic_id}/{document_id}.pdf; UPLOAD_DIR is only a local staging spot
mid-request, since the extraction pipeline (src/ingest.py) reads from a
filesystem path.
"""

import sys
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import settings
from app.deps import CurrentUser, require_clinic_admin
from app.schemas import DocumentOut

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chunk import chunk_document  # noqa: E402
from config import collection_name_for  # noqa: E402
from embed import index_chunks  # noqa: E402
from ingest import extract_pdf  # noqa: E402
from preprocessing import process_document  # noqa: E402

router = APIRouter(prefix="/documents", tags=["documents"])

STORAGE_BUCKET = "guidelines"


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    publisher: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    topic: Optional[str] = Form(None),
    admin: CurrentUser = Depends(require_clinic_admin),
):
    """
    Upload a PDF and run it through the ingestion pipeline.

    The clinic is taken from the admin's verified token, so an upload
    always lands in the caller's own tenant — RLS's documents_admin_write
    policy would reject any other clinic_id anyway, but the value is never
    even offered to the caller to begin with.
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF uploads are supported",
        )

    contents = file.file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(contents) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.MAX_UPLOAD_BYTES} bytes",
        )

    db = admin.db  # this admin's own client — every call below runs under RLS as them

    # Inserted with a placeholder file_path: the storage path is keyed by
    # this row's own generated id, so the id has to exist before the path
    # can be computed, and the path before the storage upload can happen.
    document = db.table("documents").insert({
        "clinic_id": admin.clinic_id,
        "title": title,
        "publisher": publisher,
        "source_url": source_url,
        "topic": topic,
        "file_path": "",
        "verified": False,  # guardrail #5: admin must confirm the source
    }).execute().data[0]
    document_id = document["id"]

    local_dir = settings.UPLOAD_DIR / admin.clinic_id
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"{document_id}.pdf"
    local_path.write_bytes(contents)

    def _rollback():
        db.table("documents").delete().eq("id", document_id).execute()
        local_path.unlink(missing_ok=True)

    try:
        metadata = {"title": title, "publisher": publisher, "url": source_url, "topic": topic}
        extracted = extract_pdf(str(local_path), metadata=metadata)
        preprocessed, _removed, _dropped = process_document(extracted)
        chunks = chunk_document(preprocessed, document_id=document_id)

        # persist_dir omitted, not passed as None: index_chunks's default
        # argument only applies when the parameter is left out entirely —
        # passing persist_dir=None explicitly overrides it with None,
        # which str()'s into the literal path "None" and silently writes
        # every vector to a stray ./None/ directory instead of
        # data/chroma_db/. Retrieval then finds a real chunk_count in
        # Postgres but zero vectors to search, and answers every question
        # by falling through to "no relevant sources" — indistinguishable
        # from a correctly-working system with a bad index, unless you
        # separately compare the collection's actual vector count.
        index_chunks(chunks, collection_name=collection_name_for(admin.clinic_id))

        if chunks:
            db.table("chunks").insert([
                {
                    "document_id": document_id,
                    "clinic_id": admin.clinic_id,
                    "content": c["text"],
                    "section_title": c.get("section_title"),
                    "page_number": c.get("page_number"),
                    "vector_ref": c["chunk_id"],
                }
                for c in chunks
            ]).execute()

        storage_path = f"{admin.clinic_id}/{document_id}.pdf"
        db.storage.from_(STORAGE_BUCKET).upload(
            storage_path,
            contents,
            file_options={"content-type": "application/pdf"},
        )
    except Exception as exc:
        # Leave nothing half-ingested: no document row, no chunk rows (the
        # documents row's ON DELETE CASCADE takes those with it), no
        # storage object, no local file. A partially indexed guideline is
        # worse than a failed upload — it answers questions from a fragment.
        _rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not process this PDF: {exc}",
        )

    updated = db.table("documents").update({
        "file_path": storage_path,
        "page_count": extracted.get("total_pages", 0),
        "chunk_count": len(chunks),
    }).eq("id", document_id).execute().data[0]

    local_path.unlink(missing_ok=True)

    return updated


@router.get("", response_model=List[DocumentOut])
def list_documents(admin: CurrentUser = Depends(require_clinic_admin)):
    # No .eq("clinic_id", ...) filter here by choice: RLS's documents_select
    # policy already restricts this to the admin's own clinic. Adding a
    # redundant filter would make it easy to believe the filter is what's
    # doing the isolating, when it is not.
    return admin.db.table("documents").select("*").order("uploaded_at", desc=True).execute().data


@router.patch("/{document_id}/verify", response_model=DocumentOut)
def verify_document(
    document_id: str,
    verified: bool = True,
    admin: CurrentUser = Depends(require_clinic_admin),
):
    """Confirm a source is official (guardrail #5)."""
    result = (
        admin.db.table("documents")
        .update({"verified": verified})
        .eq("id", document_id)
        .execute()
    )
    # RLS scopes the update to the admin's own clinic already; an id from
    # another clinic (or one that doesn't exist) simply matches no row,
    # which reports as missing rather than forbidden.
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return result.data[0]
