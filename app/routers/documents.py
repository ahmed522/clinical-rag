"""
Guideline upload and verification (clinic admin only).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import require_clinic_admin
from app.models import Document, User
from app.schemas import DocumentOut
from app.services.ingestion import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    publisher: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    topic: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_clinic_admin),
):
    """
    Upload a PDF and run it through the ingestion pipeline.

    The clinic is taken from the admin's token, so an upload always lands
    in the caller's own tenant.
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

    # Files are stored per clinic on disk as well as per clinic in the
    # database, so tenant separation survives someone poking at the
    # filesystem.
    clinic_dir = settings.UPLOAD_DIR / admin.clinic_id
    clinic_dir.mkdir(parents=True, exist_ok=True)

    document = Document(
        clinic_id=admin.clinic_id,
        title=title,
        publisher=publisher,
        source_url=source_url,
        topic=topic,
        file_path="",          # set below, needs the generated id
        verified=False,        # guardrail #5: admin must confirm the source
    )
    db.add(document)
    db.flush()

    destination = clinic_dir / f"{document.id}.pdf"
    destination.write_bytes(contents)
    document.file_path = str(destination)

    try:
        page_count, chunk_count = ingest_document(db, document)
    except Exception as exc:
        # Leave nothing half-ingested: no document row, no chunk rows, no
        # orphaned file. A partially indexed guideline is worse than a
        # failed upload, because it answers questions from a fragment.
        db.rollback()
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not process this PDF: {exc}",
        )

    document.page_count = page_count
    document.chunk_count = chunk_count
    db.commit()
    db.refresh(document)

    return document


@router.get("", response_model=List[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    admin: User = Depends(require_clinic_admin),
):
    return (
        db.query(Document)
        .filter(Document.clinic_id == admin.clinic_id)
        .order_by(Document.uploaded_at.desc())
        .all()
    )


@router.patch("/{document_id}/verify", response_model=DocumentOut)
def verify_document(
    document_id: str,
    verified: bool = True,
    db: Session = Depends(get_db),
    admin: User = Depends(require_clinic_admin),
):
    """Confirm a source is official (guardrail #5)."""
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.clinic_id == admin.clinic_id)
        .first()
    )
    # Filtering by clinic_id means another clinic's document is reported
    # as missing rather than forbidden, which avoids confirming it exists.
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    document.verified = verified
    db.commit()
    db.refresh(document)
    return document
