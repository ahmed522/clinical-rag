"""Audited internal IT operations for RAG monitoring and debugging."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, require_it
from app.routers.evaluation import REPORT_PATHS
from app.schemas import BugReportOut, BugReportStatusUpdate, PipelineTestRequest
from app.services.generation import answer_question
from app.services.retrieval import RetrievalUnavailableError, retrieve
from app.supabase_client import admin_client
from rag.chunk import chunk_document
from rag.config import collection_name_for
from rag.embed import index_chunks
from rag.ingest import extract_pdf
from rag.preprocessing import process_document

router = APIRouter(prefix="/it", tags=["it"])
STORAGE_BUCKET = "guidelines"


def _audit(
    user: CurrentUser,
    action: str,
    *,
    clinic_id: Optional[str] = None,
    document_id: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    """Write an immutable audit row before privileged data access.

    This intentionally fails closed. Returning cross-clinic data while its
    audit write failed would make the audit promise false.
    """
    try:
        admin_client().table("it_access_log").insert({
            "it_user_id": user.user_id,
            "action": action,
            "target_clinic_id": clinic_id,
            "target_document_id": document_id,
            "detail": detail,
        }).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IT audit log is unavailable; privileged access was not performed",
        ) from exc


@router.get("/stats", response_model=List[Dict[str, Any]])
def cross_clinic_stats(user: CurrentUser = Depends(require_it)):
    """Return aggregate counts; the SECURITY DEFINER RPC logs atomically."""
    return user.db.rpc("it_clinic_stats").execute().data or []


@router.get("/metrics", response_model=Dict[str, Any])
def rag_metrics(user: CurrentUser = Depends(require_it)):
    _audit(user, "view_metrics")
    available = [path for path in REPORT_PATHS if path.exists()]
    if not available:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No RAG evaluation report has been generated yet",
        )
    try:
        latest = max(available, key=lambda path: path.stat().st_mtime)
        with open(latest, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The latest RAG evaluation report is unavailable",
        ) from exc


@router.get("/bug-reports", response_model=List[BugReportOut])
def list_bug_reports(user: CurrentUser = Depends(require_it)):
    _audit(user, "view_bug_reports")
    return (
        admin_client()
        .table("bug_reports")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
    )


@router.patch("/bug-reports/{report_id}", response_model=BugReportOut)
def update_bug_report(
    report_id: str,
    payload: BugReportStatusUpdate,
    user: CurrentUser = Depends(require_it),
):
    _audit(
        user,
        "update_bug_report",
        detail={"report_id": report_id, "status": payload.status},
    )
    changes: Dict[str, Any] = {
        "status": payload.status,
        "resolved_at": (
            datetime.now(timezone.utc).isoformat()
            if payload.status == "resolved"
            else None
        ),
    }
    result = (
        admin_client()
        .table("bug_reports")
        .update(changes)
        .eq("id", report_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )
    return result.data[0]


@router.post("/pipeline-test", response_model=Dict[str, Any])
def pipeline_test(
    payload: PipelineTestRequest,
    user: CurrentUser = Depends(require_it),
):
    """Run one connected temporary pipeline without touching the live index.

    The extracted chunks are embedded into an isolated temporary Chroma
    collection. Retrieval searches that collection, and generation receives
    those exact hits instead of executing another search.
    """
    _audit(
        user,
        "pipeline_test",
        document_id=payload.document_id,
        detail={"question_length": len(payload.question)},
    )
    root = admin_client()
    documents = (
        root.table("documents")
        .select("*")
        .eq("id", payload.document_id)
        .execute()
        .data
    )
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    document = documents[0]
    clinic_id = document["clinic_id"]
    stages: Dict[str, Any] = {}
    hits: List[dict] = []

    with tempfile.TemporaryDirectory(prefix="clinical-rag-it-") as temp_dir:
        temp_root = Path(temp_dir)
        pdf_path = temp_root / "source.pdf"

        indexing: Dict[str, Any] = {"status": "ok"}
        try:
            storage_path = f"{clinic_id}/{payload.document_id}.pdf"
            pdf_path.write_bytes(
                root.storage.from_(STORAGE_BUCKET).download(storage_path)
            )
            metadata = {
                "title": document.get("title"),
                "publisher": document.get("publisher"),
                "url": document.get("source_url"),
                "topic": document.get("topic"),
            }
            extracted = extract_pdf(pdf_path, metadata=metadata)
            preprocessed, _removed, _dropped = process_document(extracted)
            chunks = chunk_document(
                preprocessed,
                document_id=payload.document_id,
            )
            vector_count = index_chunks(
                chunks,
                collection_name=collection_name_for(clinic_id),
                persist_dir=temp_root,
            )
            report = extracted.get("extraction_report", {}) or {}
            indexing.update({
                "total_pages": extracted.get("total_pages", 0),
                "extracted_pages": extracted.get("extracted_pages", 0),
                "char_count": sum(
                    page.get("char_count", 0)
                    for page in extracted.get("pages", [])
                ),
                "chunk_count": len(chunks),
                "vector_count": vector_count,
                "warnings": report.get("warnings", []),
                "sample_chunks": [
                    {
                        "chunk_id": chunk.get("chunk_id"),
                        "page_number": chunk.get("page_number"),
                        "section_title": chunk.get("section_title"),
                        "text": (chunk.get("text") or "")[:600],
                    }
                    for chunk in chunks[:3]
                ],
            })
        except Exception as exc:
            indexing = {
                "status": "error",
                "error": str(exc)[:1000],
                "code": getattr(exc, "code", None),
            }
        stages["indexing"] = indexing

        if indexing["status"] == "ok":
            retrieval_stage: Dict[str, Any] = {"status": "ok"}
            try:
                hits = retrieve(
                    clinic_id,
                    payload.question,
                    persist_dir=temp_root,
                    document_ids=[payload.document_id],
                )
                retrieval_stage.update({
                    "hit_count": len(hits),
                    "hits": [
                        {
                            "rank": hit.get("rank"),
                            "chunk_id": hit.get("chunk_id"),
                            "page_number": hit.get("page_number"),
                            "section_title": hit.get("section_title"),
                            "vector_distance": hit.get("distance"),
                            "rerank_score": hit.get("rerank_score"),
                            "text": (hit.get("text") or "")[:600],
                        }
                        for hit in hits
                    ],
                })
            except RetrievalUnavailableError as exc:
                retrieval_stage = {
                    "status": "error",
                    "error": f"retrieval_unavailable: {exc}",
                }
            except Exception as exc:
                retrieval_stage = {"status": "error", "error": str(exc)[:1000]}
        else:
            retrieval_stage = {"status": "not_reached"}
        stages["retrieval"] = retrieval_stage

        if retrieval_stage["status"] == "ok":
            generation_stage: Dict[str, Any] = {"status": "ok"}
            try:
                answer = answer_question(
                    clinic_id=clinic_id,
                    question=payload.question,
                    role="doctor",
                    document_ids=[payload.document_id],
                    pre_retrieved_sources=hits,
                )
                generation_stage.update({
                    "grounded": answer.grounded,
                    "reason": answer.reason,
                    "evidence_strength": answer.evidence_strength,
                    "final_answer": answer.text,
                    "citations": answer.citations or [],
                    "evidence": answer.evidence,
                    "audit": answer.audit,
                })
            except Exception as exc:
                generation_stage = {
                    "status": "error",
                    "error": str(exc)[:1000],
                }
        else:
            generation_stage = {"status": "not_reached"}
        stages["generation"] = generation_stage

    return {
        "document": {
            "id": document["id"],
            "title": document.get("title"),
            "clinic_id": clinic_id,
            "status": document.get("status"),
            "verified": document.get("verified"),
        },
        "question": payload.question,
        "stages": stages,
    }
