"""Doctor chat over verified clinic guidelines, with doctor-private history."""

from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, require_doctor
from app.llm_prompts import PROMPT_VERSION
from app.routers.chat import _verified_document_ids
from app.schemas import (
    DoctorChatReply,
    DoctorChatRequest,
    DoctorChatSessionOut,
    DoctorMessageOut,
)
from app.services.generation import GroundedAnswer, answer_question

router = APIRouter(prefix="/doctor", tags=["doctor"])


def _doctor_record(doctor: CurrentUser) -> dict:
    result = doctor.db.table("doctors").select("id").eq("auth_id", doctor.user_id).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No doctor record linked to this account",
        )
    return result.data[0]


def _get_session(doctor: CurrentUser, session_id: str) -> dict:
    result = doctor.db.table("doctor_chat_sessions").select("*").eq("id", session_id).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    return result.data[0]


def _insert_assistant_message(
    doctor: CurrentUser, session_id: str, answer: GroundedAnswer
) -> dict:
    return (
        doctor.db.table("doctor_chat_messages")
        .insert(
            {
                "session_id": session_id,
                "clinic_id": doctor.clinic_id,
                "role": "assistant",
                "content": answer.text,
                "citations": answer.citations or None,
                "grounded": answer.grounded,
                "reason": answer.reason,
                "evidence_strength": answer.evidence_strength,
                "evidence": answer.evidence,
                "prompt_version": answer.audit.get("prompt_version") or PROMPT_VERSION,
                "rag_metadata": answer.audit or None,
            }
        )
        .execute()
        .data[0]
    )


@router.post("/chat/sessions", response_model=DoctorChatSessionOut, status_code=status.HTTP_201_CREATED)
def create_doctor_session(doctor: CurrentUser = Depends(require_doctor)):
    record = _doctor_record(doctor)
    return (
        doctor.db.table("doctor_chat_sessions")
        .insert({"clinic_id": doctor.clinic_id, "doctor_id": record["id"]})
        .execute()
        .data[0]
    )


@router.get("/chat/sessions", response_model=List[DoctorChatSessionOut])
def list_doctor_sessions(doctor: CurrentUser = Depends(require_doctor)):
    record = _doctor_record(doctor)
    sessions = (
        doctor.db.table("doctor_chat_sessions")
        .select("id, started_at")
        .eq("doctor_id", record["id"])
        .order("started_at", desc=True)
        .execute()
        .data
    )
    if not sessions:
        return []
    rows = (
        doctor.db.table("doctor_chat_messages")
        .select("session_id")
        .in_("session_id", [session["id"] for session in sessions])
        .execute()
        .data
    )
    counts = Counter(row["session_id"] for row in rows)
    return [
        {**session, "message_count": counts[session["id"]]}
        for session in sessions
        if counts[session["id"]] > 0
    ]


@router.get("/chat/{session_id}", response_model=List[DoctorMessageOut])
def doctor_session_history(session_id: str, doctor: CurrentUser = Depends(require_doctor)):
    _get_session(doctor, session_id)
    return (
        doctor.db.table("doctor_chat_messages")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .execute()
        .data
    )


@router.post("/chat/{session_id}/message", response_model=DoctorMessageOut)
def send_doctor_message(
    session_id: str,
    payload: DoctorChatRequest,
    doctor: CurrentUser = Depends(require_doctor),
):
    _get_session(doctor, session_id)
    doctor.db.table("doctor_chat_messages").insert(
        {
            "session_id": session_id,
            "clinic_id": doctor.clinic_id,
            "role": "user",
            "content": payload.content,
        }
    ).execute()
    answer = answer_question(
        clinic_id=doctor.clinic_id,
        question=payload.content,
        role="doctor",
        document_ids=_verified_document_ids(doctor),
    )
    return _insert_assistant_message(doctor, session_id, answer)


@router.post("/chat", response_model=DoctorChatReply)
def doctor_chat(payload: DoctorChatRequest, doctor: CurrentUser = Depends(require_doctor)):
    """Compatibility single-turn endpoint; the dashboard uses persisted sessions."""
    answer = answer_question(
        clinic_id=doctor.clinic_id,
        question=payload.content,
        role="doctor",
        document_ids=_verified_document_ids(doctor),
    )
    return DoctorChatReply(
        content=answer.text,
        grounded=answer.grounded,
        reason=answer.reason,
        citations=answer.citations or None,
        evidence_strength=answer.evidence_strength,
        evidence=answer.evidence,
    )
