"""
Patient chat: grounded, cited answers from the patient's own clinic.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_patient
from app.models import ChatSession, MedicalRecord, Message, Patient
from app.schemas import ChatReply, MessageIn, MessageOut, SessionCreate, SessionOut
from app.services.generation import answer_question

router = APIRouter(prefix="/chat", tags=["chat"])


def _patient_context(db: Session, patient: Patient) -> str:
    """
    A short summary of the patient's own records, for consult/triage.

    Scoped by both patient_id and clinic_id. Used only to judge which
    guidance is relevant — never as a substitute for a cited source.
    """
    records = (
        db.query(MedicalRecord)
        .filter(
            MedicalRecord.patient_id == patient.id,
            MedicalRecord.clinic_id == patient.clinic_id,
        )
        .order_by(MedicalRecord.created_at.desc())
        .limit(5)
        .all()
    )
    return "\n".join(
        f"- {r.diagnosis or 'note'}: {r.notes or ''}".strip() for r in records
    )


def _get_session(db: Session, session_id: str, patient: Patient) -> ChatSession:
    session = (
        db.query(ChatSession)
        .filter(
            ChatSession.id == session_id,
            ChatSession.patient_id == patient.id,
            ChatSession.clinic_id == patient.clinic_id,
        )
        .first()
    )
    # Scoped by patient AND clinic: another patient's session reads as
    # missing rather than forbidden, so its existence is not confirmed.
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    patient: Patient = Depends(current_patient),
):
    session = ChatSession(
        patient_id=patient.id,
        clinic_id=patient.clinic_id,
        mode=payload.mode,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/message", response_model=ChatReply)
def send_message(
    session_id: str,
    payload: MessageIn,
    db: Session = Depends(get_db),
    patient: Patient = Depends(current_patient),
):
    """
    Answer a patient's question from their clinic's documents only.

    Retrieval is scoped to the patient's clinic via their token, so no
    request can widen it.
    """
    session = _get_session(db, session_id, patient)

    db.add(
        Message(
            session_id=session.id,
            clinic_id=patient.clinic_id,
            role="user",
            content=payload.content,
        )
    )

    context = ""
    if session.mode in ("consult", "triage"):
        context = _patient_context(db, patient)

    answer = answer_question(
        clinic_id=patient.clinic_id,
        question=payload.content,
        mode=session.mode,
        patient_context=context,
    )

    reply = Message(
        session_id=session.id,
        clinic_id=patient.clinic_id,
        role="assistant",
        content=answer.text,
        citations=answer.citations or None,
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)

    return ChatReply(
        message=MessageOut.model_validate(reply),
        grounded=answer.grounded,
        reason=answer.reason,
    )


@router.get("/{session_id}", response_model=List[MessageOut])
def session_history(
    session_id: str,
    db: Session = Depends(get_db),
    patient: Patient = Depends(current_patient),
):
    session = _get_session(db, session_id, patient)
    return (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.created_at.asc())
        .all()
    )
