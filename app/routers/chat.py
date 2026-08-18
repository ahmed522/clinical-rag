"""
Patient chat: grounded, cited answers from the patient's own clinic.

Every query in this file runs through the patient's OWN Supabase client
(current_patient_record's caller, forwarded from deps.py), so RLS is doing
the tenant- and ownership-scoping — not the .eq() filters sprinkled below,
which exist for readability and would still be redundant-but-harmless if
ever dropped. The one exception worth naming explicitly: resolving which
documents may ground an answer. That one-line query IS guardrail #5 —
documents_select's RLS policy hides unverified rows from a patient
entirely, so "documents visible to this caller" and "documents allowed to
answer this caller" are the same query by construction.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, current_patient_record, require_patient
from app.schemas import ChatReply, MessageIn, MessageOut, SessionCreate, SessionOut
from app.services.generation import answer_question

router = APIRouter(prefix="/chat", tags=["chat"])


def _patient_context(user: CurrentUser, patient: dict) -> str:
    """A short summary of the patient's own records, for consult/triage."""
    records = (
        user.db.table("medical_records")
        .select("diagnosis, notes")
        .eq("patient_id", patient["id"])
        .order("created_at", desc=True)
        .limit(5)
        .execute()
        .data
    )
    return "\n".join(
        f"- {r.get('diagnosis') or 'note'}: {r.get('notes') or ''}".strip() for r in records
    )


def _verified_document_ids(user: CurrentUser) -> List[str]:
    rows = user.db.table("documents").select("id").eq("verified", True).execute().data
    return [row["id"] for row in rows]


def _get_session(user: CurrentUser, session_id: str) -> dict:
    result = user.db.table("chat_sessions").select("*").eq("id", session_id).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return result.data[0]


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    user: CurrentUser = Depends(require_patient),
    patient: dict = Depends(current_patient_record),
):
    return (
        user.db.table("chat_sessions")
        .insert({"clinic_id": user.clinic_id, "patient_id": patient["id"], "mode": payload.mode})
        .execute()
        .data[0]
    )


@router.post("/{session_id}/message", response_model=ChatReply)
def send_message(
    session_id: str,
    payload: MessageIn,
    user: CurrentUser = Depends(require_patient),
    patient: dict = Depends(current_patient_record),
):
    """
    Answer a patient's question from their clinic's VERIFIED documents only.

    Retrieval is scoped to the patient's clinic via their token, so no
    request can widen it, and narrowed again to documents the clinic has
    confirmed are official.
    """
    session = _get_session(user, session_id)

    user.db.table("messages").insert({
        "session_id": session["id"],
        "clinic_id": user.clinic_id,
        "role": "user",
        "content": payload.content,
    }).execute()

    context = ""
    if session["mode"] in ("consult", "triage"):
        context = _patient_context(user, patient)

    answer = answer_question(
        clinic_id=user.clinic_id,
        question=payload.content,
        mode=session["mode"],
        patient_context=context,
        document_ids=_verified_document_ids(user),
    )

    reply = (
        user.db.table("messages")
        .insert({
            "session_id": session["id"],
            "clinic_id": user.clinic_id,
            "role": "assistant",
            "content": answer.text,
            "citations": answer.citations or None,
        })
        .execute()
        .data[0]
    )

    return ChatReply(
        message=MessageOut.model_validate(reply),
        grounded=answer.grounded,
        reason=answer.reason,
    )


@router.get("/{session_id}", response_model=List[MessageOut])
def session_history(
    session_id: str,
    user: CurrentUser = Depends(require_patient),
):
    session = _get_session(user, session_id)
    return (
        user.db.table("messages")
        .select("*")
        .eq("session_id", session["id"])
        .order("created_at", desc=False)
        .execute()
        .data
    )
