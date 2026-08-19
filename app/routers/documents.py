"""
Guideline upload and verification (doctor only).

Ownership moved here from the clinic admin: uploading and verifying RAG
source documents is medical judgment about what's authoritative, not an
administrative task, so it lives with the doctor role — the admin has no
access to this router at all (enforced both here, as the first friendly
403, and independently by RLS's documents_doctor_write policy).

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

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.config import settings
from app.deps import CurrentUser, require_doctor
from app.schemas import DocumentOut

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chunk import chunk_document  # noqa: E402
from config import CHUNKING_VERSION, EXTRACTION_VERSION, collection_name_for  # noqa: E402
from embed import delete_document_chunks, index_chunks  # noqa: E402
from ingest import PDFExtractionError, extract_pdf  # noqa: E402
from preprocessing import process_document  # noqa: E402

router = APIRouter(prefix="/documents", tags=["documents"])

STORAGE_BUCKET = "guidelines"


def _has_pdf_signature(contents: bytes) -> bool:
    """PDF headers may follow a few transport bytes, but must appear near the start."""

    return b"%PDF-" in contents[:1024]


def _cleanup_partial_ingestion(db, document_id: str, clinic_id: str, storage_path: str) -> List[str]:
    """Best-effort compensation across Chroma, Storage, and PostgreSQL."""

    errors = []
    try:
        delete_document_chunks(
            document_id,
            collection_name=collection_name_for(clinic_id),
        )
    except Exception as exc:
        errors.append(f"vector cleanup failed: {exc}")

    try:
        # Attempt removal even when upload raised because a partial object may exist.
        db.storage.from_(STORAGE_BUCKET).remove([storage_path])
    except Exception as exc:
        errors.append(f"storage cleanup failed: {exc}")

    try:
        db.table("chunks").delete().eq("document_id", document_id).execute()
    except Exception as exc:
        errors.append(f"chunk-row cleanup failed: {exc}")

    return errors


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    publisher: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    topic: Optional[str] = Form(None),
    doctor: CurrentUser = Depends(require_doctor),
):
    """
    Upload a PDF and run it through the ingestion pipeline.

    The clinic is taken from the doctor's verified token, so an upload
    always lands in the caller's own tenant — RLS's documents_doctor_write
    policy would reject any other clinic_id anyway, but the value is never
    even offered to the caller to begin with.
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF uploads are supported",
        )

    # Read at most one byte beyond the limit so an oversized upload does not
    # have to be fully buffered before it can be rejected.
    contents = file.file.read(settings.MAX_UPLOAD_BYTES + 1)
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(contents) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.MAX_UPLOAD_BYTES} bytes",
        )

    if not _has_pdf_signature(contents):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not a valid PDF",
        )

    db = doctor.db  # this doctor's own client — every call below runs under RLS as them

    file_sha256 = hashlib.sha256(contents).hexdigest()

    # Inserted with a placeholder file_path: the storage path is keyed by
    # this row's own generated id, so the id has to exist before the path
    # can be computed, and the path before the storage upload can happen.
    document = db.table("documents").insert({
        "clinic_id": doctor.clinic_id,
        "title": title,
        "publisher": publisher,
        "source_url": source_url,
        "topic": topic,
        "file_path": "",
        "verified": False,
        "status": "processing",
        "processing_error": None,
        "uploaded_by": doctor.user_id,
        "file_sha256": file_sha256,
        "extraction_version": EXTRACTION_VERSION,
        "chunking_version": CHUNKING_VERSION,
    }).execute().data[0]
    document_id = document["id"]
    storage_path = f"{doctor.clinic_id}/{document_id}.pdf"

    local_dir = settings.UPLOAD_DIR / doctor.clinic_id
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"{document_id}.pdf"

    try:
        local_path.write_bytes(contents)
        metadata = {"title": title, "publisher": publisher, "url": source_url, "topic": topic}
        extracted = extract_pdf(str(local_path), metadata=metadata)
        preprocessed, _removed, _dropped = process_document(extracted)
        chunks = chunk_document(preprocessed, document_id=document_id)
        if not chunks:
            raise PDFExtractionError(
                "The PDF produced no searchable chunks after preprocessing.",
                code="no_chunks",
                report=extracted.get("extraction_report", {}),
            )

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
        index_chunks(chunks, collection_name=collection_name_for(doctor.clinic_id))

        if chunks:
            db.table("chunks").insert([
                {
                    "document_id": document_id,
                    "clinic_id": doctor.clinic_id,
                    "content": c["text"],
                    "section_title": c.get("section_title"),
                    "page_number": c.get("page_number"),
                    "vector_ref": c["chunk_id"],
                }
                for c in chunks
            ]).execute()

        db.storage.from_(STORAGE_BUCKET).upload(
            storage_path,
            contents,
            file_options={"content-type": "application/pdf"},
        )

        updated_rows = db.table("documents").update({
            "status": "ready",
            "processing_error": None,
            "file_path": storage_path,
            "page_count": extracted.get("total_pages", 0),
            "chunk_count": len(chunks),
            "extraction_report": extracted.get("extraction_report", {}),
        }).eq("id", document_id).execute().data
        if not updated_rows:
            raise RuntimeError("Document row disappeared while finalizing ingestion")
        updated = updated_rows[0]
    except Exception as exc:
        # Keep the document row as a visible failed attempt, but remove every
        # searchable or stored artifact. Failed/processing rows are excluded
        # from patient retrieval even if an infrastructure cleanup also fails.
        cleanup_errors = _cleanup_partial_ingestion(
            db,
            document_id=document_id,
            clinic_id=doctor.clinic_id,
            storage_path=storage_path,
        )
        failure_message = str(exc)[:1500]
        if cleanup_errors:
            failure_message += " | " + " | ".join(cleanup_errors)

        failure_update = {
            "status": "failed",
            "verified": False,
            "processing_error": failure_message[:2000],
            "file_path": "",
            "chunk_count": 0,
            "extraction_report": getattr(exc, "report", {}),
        }
        try:
            db.table("documents").update(failure_update).eq("id", document_id).execute()
        except Exception:
            # A stuck `processing` row remains non-retrievable and visible
            # to the doctor for manual cleanup.
            pass
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not process this PDF: {failure_message}",
        )

    finally:
        local_path.unlink(missing_ok=True)

    return updated


@router.get("", response_model=List[DocumentOut])
def list_documents(doctor: CurrentUser = Depends(require_doctor)):
    # No .eq("clinic_id", ...) filter here by choice: RLS's documents_select
    # policy already restricts this to the doctor's own clinic. Adding a
    # redundant filter would make it easy to believe the filter is what's
    # doing the isolating, when it is not.
    return doctor.db.table("documents").select("*").order("uploaded_at", desc=True).execute().data


@router.patch("/{document_id}/verify", response_model=DocumentOut)
def verify_document(
    document_id: str,
    verified: bool = True,
    doctor: CurrentUser = Depends(require_doctor),
):
    """Confirm a ready source is doctor-approved for patient answers."""
    changes = {
        "verified": verified,
        "verified_by": doctor.user_id if verified else None,
        "verified_at": datetime.now(timezone.utc).isoformat() if verified else None,
    }
    query = doctor.db.table("documents").update(changes).eq("id", document_id)
    if verified:
        query = query.eq("status", "ready")
    result = query.execute()
    # RLS scopes the update to the doctor's own clinic already; an id from
    # another clinic (or one that doesn't exist) simply matches no row,
    # which reports as missing rather than forbidden.
    if not result.data:
        detail = "Document is not ready for verification" if verified else "Document not found"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return result.data[0]
