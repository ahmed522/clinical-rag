from pathlib import Path

import pytest
from fastapi import HTTPException

from app.deps import require_it
from app.routers import doctor as doctor_router
from app.routers import it as it_router
from app.schemas import AppointmentActionIn, DoctorChatRequest, SessionCreate
from app.services import classifier
from app.services.appointments import apply_appointment_action, handle_appointment_query
from app.services.generation import GroundedAnswer


def _user(role="doctor"):
    return type(
        "User",
        (),
        {
            "user_id": "user-1",
            "clinic_id": "clinic-1",
            "role": role,
            "db": object(),
        },
    )()


def test_it_dependency_rejects_non_it_role():
    with pytest.raises(HTTPException) as exc:
        require_it(_user("doctor"))
    assert exc.value.status_code == 403


def test_doctor_chat_selects_role_from_authenticated_user(monkeypatch):
    captured = {}

    def answer_question(**kwargs):
        captured.update(kwargs)
        return GroundedAnswer("Grounded answer", grounded=True)

    monkeypatch.setattr(doctor_router, "_verified_document_ids", lambda _user: ["doc-1"])
    monkeypatch.setattr(doctor_router, "answer_question", answer_question)

    reply = doctor_router.doctor_chat(
        DoctorChatRequest(content="What does the guideline recommend?"),
        _user("doctor"),
    )

    assert reply.grounded is True
    assert captured["role"] == "doctor"
    assert captured["clinic_id"] == "clinic-1"
    assert captured["document_ids"] == ["doc-1"]


def test_it_audit_failure_fails_closed(monkeypatch):
    class BrokenQuery:
        def insert(self, _payload):
            return self

        def execute(self):
            raise RuntimeError("audit unavailable")

    class BrokenAdmin:
        def table(self, name):
            assert name == "it_access_log"
            return BrokenQuery()

    monkeypatch.setattr(it_router, "admin_client", lambda: BrokenAdmin())
    with pytest.raises(HTTPException) as exc:
        it_router._audit(_user("it"), "view_metrics")
    assert exc.value.status_code == 503


def test_role_migration_keeps_cross_clinic_access_behind_audited_api():
    migration = (
        Path(__file__).resolve().parents[1]
        / "supabase"
        / "migrations"
        / "0008_receptionist_it_roles.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.lower().split())

    assert migration.index("create or replace function public.is_it") < migration.index(
        "drop policy if exists documents_select"
    )
    assert "or public.is_it()" not in normalized
    assert "drop policy if exists guidelines_it_read" in normalized
    assert "public.auth_role() = 'patient'" in normalized
    assert "reported_by = auth.uid()" in normalized
    assert "grant select, insert, update, delete on all tables" not in normalized


def test_patient_availability_question_uses_deterministic_routing():
    intent, greeting = classifier.classify_query("Which doctors are available now?")
    assert intent == classifier.QueryIntent.AVAILABILITY
    assert greeting is None


def test_booking_actions_and_medical_refusal_are_deterministic():
    assert classifier.classify_query("Please book an appointment")[0] == classifier.QueryIntent.BOOK
    assert classifier.classify_query("I need to reschedule my appointment")[0] == classifier.QueryIntent.RESCHEDULE
    assert classifier.classify_query("Cancel my appointment")[0] == classifier.QueryIntent.CANCEL
    assert classifier.classify_query("I have chest pain and cannot breathe")[0] == classifier.QueryIntent.MEDICAL
    assert classifier.classify_query("What dose should I take?")[0] == classifier.QueryIntent.MEDICAL


def test_patient_chat_creates_general_sessions_and_requires_booking_confirmation():
    assert SessionCreate().mode == "general"
    with pytest.raises(Exception):
        SessionCreate(mode="triage")

    with pytest.raises(ValueError, match="confirm"):
        apply_appointment_action(
            _user("patient"),
            AppointmentActionIn(action="book", confirmed=False),
        )


def test_doctor_history_message_persists_user_and_structured_assistant(monkeypatch):
    inserted = []

    class InsertQuery:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            inserted.append(self.payload)
            return type(
                "Result",
                (),
                {"data": [{**self.payload, "id": f"message-{len(inserted)}", "created_at": "2026-01-01T00:00:00Z"}]},
            )()

    class MessagesTable:
        def insert(self, payload):
            return InsertQuery(payload)

    class Db:
        def table(self, name):
            assert name == "doctor_chat_messages"
            return MessagesTable()

    user = _user("doctor")
    user.db = Db()
    monkeypatch.setattr(doctor_router, "_get_session", lambda *_args: {"id": "session-1"})
    monkeypatch.setattr(doctor_router, "_verified_document_ids", lambda _user: ["doc-1"])
    monkeypatch.setattr(
        doctor_router,
        "answer_question",
        lambda **_kwargs: GroundedAnswer(
            "Guideline answer", citations=[{"document": "Guideline"}], grounded=True,
            evidence={"evidence_strength": "medium"}, audit={"prompt_version": "test"},
        ),
    )

    reply = doctor_router.send_doctor_message(
        "session-1", DoctorChatRequest(content="What does the guideline say?"), user
    )

    assert reply["role"] == "assistant"
    assert [row["role"] for row in inserted] == ["user", "assistant"]
    assert inserted[1]["prompt_version"] == "test"


def test_available_doctors_reply_is_friendly_and_does_not_query_appointments(monkeypatch):
    class Result:
        def __init__(self, data):
            self.data = data

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_args): return self
        def eq(self, *_args): return self
        def order(self, *_args, **_kwargs): return self
        def execute(self): return Result(self.rows)

    class Db:
        def table(self, name):
            assert name in {"doctors", "doctor_availability"}
            if name == "doctors":
                return Query([{"id": "doctor-1", "name": "Nora", "specialty": "Endocrinology"}])
            return Query([])

    user = _user("patient")
    user.db = Db()
    answer = handle_appointment_query(user, "Which doctors are available now?")
    assert answer.grounded is True
    assert "Dr. Nora" in answer.text
    assert "Appointments page" in answer.text
