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

from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, current_patient_record, require_patient
from app.schemas import ChatReply, MessageIn, MessageOut, SessionCreate, SessionOut
from app.llm_prompts import PROMPT_VERSION
from app.services.appointments import handle_appointment_query
from app.services.classifier import QueryIntent, classify_query
from app.services.generation import GroundedAnswer, answer_question

GREETING_RESPONSES = {
    "hello": (
        "Hello! I'm your clinic's health assistant. You can ask me "
        "medical questions or check your appointments. How can I help?"
    ),
    "thanks": "You're welcome! Let me know if there's anything else I can help with.",
    "farewell": "Goodbye! Take care, and don't hesitate to reach out if you need anything.",
}

router = APIRouter(prefix="/chat", tags=["chat"])


def _insert_assistant_message(user: CurrentUser, session_id: str, answer: GroundedAnswer) -> dict:
    """Persist the additive evidence audit, with a pre-migration compatibility path."""
    base = {
        "session_id": session_id,
        "clinic_id": user.clinic_id,
        "role": "assistant",
        "content": answer.text,
        "citations": answer.citations or None,
    }
    enriched = {
        **base,
        "grounded": answer.grounded,
        "reason": answer.reason,
        "evidence_strength": answer.evidence_strength,
        "evidence": answer.evidence,
        "prompt_version": answer.audit.get("prompt_version") or PROMPT_VERSION,
        "rag_metadata": answer.audit or None,
    }
    try:
        row = user.db.table("messages").insert(enriched).execute().data[0]
    except Exception as exc:
        message = str(exc).lower()
        if not any(name in message for name in ("evidence", "grounded", "rag_metadata", "schema cache")):
            raise
        row = user.db.table("messages").insert(base).execute().data[0]

    # The current response is rich even during the short rollout window before
    # migration 0004 is applied. History becomes rich as soon as the columns exist.
    return {
        **row,
        "grounded": answer.grounded,
        "reason": answer.reason,
        "evidence_strength": answer.evidence_strength,
        "evidence": answer.evidence,
        "prompt_version": answer.audit.get("prompt_version") or PROMPT_VERSION,
        "rag_metadata": answer.audit or None,
    }


def _patient_context(user: CurrentUser, patient: dict) -> str:
    """A short summary of the patient's own records, for triage."""
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
    rows = (
        user.db.table("documents")
        .select("id")
        .eq("status", "ready")
        .eq("verified", True)
        .execute()
        .data
    )
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


@router.get("/sessions", response_model=List[SessionOut])
def list_sessions(
    user: CurrentUser = Depends(require_patient),
    patient: dict = Depends(current_patient_record),
):
    """
    Past sessions the patient can switch back to.

    Every mode switch in the frontend starts a fresh session (see
    create_session above), so a patient can easily accumulate sessions
    with zero messages in them just by clicking between tabs. Those are
    filtered out here rather than shown — an empty entry in a history
    list looks like a bug, not a feature.

    Registered before GET /{session_id} below: Starlette matches routes
    in registration order, so "/sessions" must come first or it would be
    captured as session_id="sessions".
    """
    sessions = (
        user.db.table("chat_sessions")
        .select("id, mode, started_at")
        .eq("patient_id", patient["id"])
        .order("started_at", desc=True)
        .execute()
        .data
    )
    if not sessions:
        return []

    messages = (
        user.db.table("messages")
        .select("session_id")
        .in_("session_id", [s["id"] for s in sessions])
        .execute()
        .data
    )
    counts = Counter(m["session_id"] for m in messages)
    return [
        {**s, "message_count": counts[s["id"]]}
        for s in sessions
        if counts[s["id"]] > 0
    ]


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

    intent, greeting_type = classify_query(payload.content)

    if intent == QueryIntent.GREETING:
        key = greeting_type.value if greeting_type else "hello"
        answer = GroundedAnswer(GREETING_RESPONSES.get(key, GREETING_RESPONSES["hello"]), grounded=True)
    elif intent == QueryIntent.APPOINTMENT:
        answer = handle_appointment_query(user, payload.content)
    else:
        context = ""
        if session["mode"] == "triage":
            context = _patient_context(user, patient)

        answer = answer_question(
            clinic_id=user.clinic_id,
            question=payload.content,
            mode=session["mode"],
            patient_context=context,
            document_ids=_verified_document_ids(user),
        )

    reply = _insert_assistant_message(user, session["id"], answer)

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
