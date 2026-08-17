"""
End-to-end API tests covering the demo success criteria (PRD sec.13).

Exercises the real stack — FastAPI, SQLAlchemy, the ingestion pipeline,
Chroma and the generation layer — against a temporary database and vector
store, with the two guideline PDFs as clinic uploads.

Criteria covered here:
  #1 a clinic uploads a guideline and it is ingested
  #2 a patient gets a cited answer grounded in that clinic's document
  #3 a second clinic's document does not leak into the first's answers
  #4 an out-of-scope question returns the honest fallback

Run with:
    python -m pytest tests/test_end_to_end.py -v
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "data" / "source"

pytestmark = pytest.mark.skipif(
    not (SOURCE_DIR / "source1.pdf").exists(),
    reason="guideline PDFs not present",
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """
    A TestClient wired to a throwaway database, upload dir and vector store.

    Environment is set before app modules are imported, since settings are
    read at import time.
    """
    tmp = tmp_path_factory.mktemp("e2e")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'test.db'}"
    os.environ["JWT_SECRET"] = "test-secret"
    os.environ["LLM_PROVIDER"] = "mock"

    for module in list(sys.modules):
        if module == "app" or module.startswith("app."):
            del sys.modules[module]

    from fastapi.testclient import TestClient

    from app.config import settings
    from app.db import init_db
    from app.main import app

    settings.UPLOAD_DIR = tmp / "uploads"

    # Point retrieval and ingestion at a temporary Chroma directory so the
    # tests never read or write the real index.
    chroma_dir = tmp / "chroma"
    import app.services.generation as generation
    import app.services.ingestion as ingestion
    import app.services.retrieval as retrieval

    original_retrieve = retrieval.retrieve
    original_ingest = ingestion.ingest_document

    def retrieve_tmp(clinic_id, question, k=8, persist_dir=None):
        return original_retrieve(clinic_id, question, k, persist_dir=chroma_dir)

    def ingest_tmp(db, document, persist_dir=None):
        return original_ingest(db, document, persist_dir=chroma_dir)

    retrieval.retrieve = retrieve_tmp
    generation.retrieve = retrieve_tmp
    ingestion.ingest_document = ingest_tmp

    import app.routers.documents as documents_router

    documents_router.ingest_document = ingest_tmp

    init_db()
    return TestClient(app)


def _register_clinic(client, name, email):
    response = client.post(
        "/auth/register-clinic",
        json={
            "clinic_name": name,
            "specialty": "Endocrinology",
            "admin_email": email,
            "admin_password": "demo-password-123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _upload(client, token, pdf_name, title):
    with open(SOURCE_DIR / pdf_name, "rb") as handle:
        response = client.post(
            "/documents/upload",
            headers=_auth(token),
            files={"file": (pdf_name, handle, "application/pdf")},
            data={"title": title, "publisher": "Test Publisher"},
        )
    assert response.status_code == 201, response.text
    return response.json()


def _patient_token(client, admin_token, name, email):
    response = client.post(
        "/auth/register-patient",
        headers=_auth(admin_token),
        json={"name": name, "email": email, "password": "patient-password-123"},
    )
    assert response.status_code == 201, response.text

    login = client.post(
        "/auth/login", json={"email": email, "password": "patient-password-123"}
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def _ask(client, token, question, mode="general"):
    session = client.post(
        "/chat/sessions", headers=_auth(token), json={"mode": mode}
    )
    assert session.status_code == 201, session.text

    reply = client.post(
        f"/chat/{session.json()['id']}/message",
        headers=_auth(token),
        json={"content": question},
    )
    assert reply.status_code == 200, reply.text
    return reply.json()


@pytest.fixture(scope="module")
def two_clinics(client):
    """Clinic A holds the NICE guideline, clinic B holds the WHO one."""
    a = _register_clinic(client, "Clinic A", "admin-a@example.com")
    b = _register_clinic(client, "Clinic B", "admin-b@example.com")

    _upload(client, a["access_token"], "source1.pdf", "NICE NG28 Type 2 Diabetes")
    _upload(client, b["access_token"], "source2.pdf", "WHO HEARTS-D Diabetes")

    return {
        "a": a,
        "b": b,
        "patient_a": _patient_token(client, a["access_token"], "Alice", "alice@example.com"),
        "patient_b": _patient_token(client, b["access_token"], "Bob", "bob@example.com"),
    }


# ----------------------------------------------------------------------
# Criterion #1 — upload and ingestion
# ----------------------------------------------------------------------

def test_upload_ingests_and_scopes_to_clinic(client, two_clinics):
    response = client.get("/documents", headers=_auth(two_clinics["a"]["access_token"]))
    assert response.status_code == 200

    documents = response.json()
    assert len(documents) == 1, "clinic A should see only its own document"
    assert documents[0]["chunk_count"] > 0
    assert documents[0]["page_count"] > 0
    assert documents[0]["verified"] is False, "uploads start unverified (guardrail #5)"


def test_clinic_cannot_see_another_clinics_documents(client, two_clinics):
    a_docs = client.get("/documents", headers=_auth(two_clinics["a"]["access_token"])).json()
    b_docs = client.get("/documents", headers=_auth(two_clinics["b"]["access_token"])).json()

    assert {d["title"] for d in a_docs}.isdisjoint({d["title"] for d in b_docs})


# ----------------------------------------------------------------------
# Criterion #2 — grounded, cited answer
# ----------------------------------------------------------------------

def test_patient_gets_cited_answer_from_own_clinic(client, two_clinics):
    reply = _ask(
        client,
        two_clinics["patient_a"],
        "What is the first-line treatment for type 2 diabetes?",
    )

    assert reply["grounded"] is True, reply
    assert reply["message"]["citations"], "a grounded answer must carry citations"

    for citation in reply["message"]["citations"]:
        assert citation["document"], "every citation names its document"
        assert citation["page"] is not None, "every citation names a page to verify"


# ----------------------------------------------------------------------
# Criterion #3 — isolation
# ----------------------------------------------------------------------

def test_answers_never_cite_another_clinics_document(client, two_clinics):
    """Clinic A's patient must never be answered from clinic B's guideline."""
    reply = _ask(
        client,
        two_clinics["patient_a"],
        "How should hypoglycaemia be managed?",
    )

    for citation in reply["message"]["citations"] or []:
        assert "WHO" not in citation["document"], (
            f"clinic B's document leaked into clinic A's answer: {citation}"
        )


def test_patient_cannot_read_another_clinics_session(client, two_clinics):
    session = client.post(
        "/chat/sessions",
        headers=_auth(two_clinics["patient_a"]),
        json={"mode": "general"},
    ).json()

    stolen = client.get(
        f"/chat/{session['id']}", headers=_auth(two_clinics["patient_b"])
    )
    assert stolen.status_code == 404, "another clinic's session must not be readable"


# ----------------------------------------------------------------------
# Criterion #4 — honest fallback
# ----------------------------------------------------------------------

def test_out_of_scope_question_returns_fallback(client, two_clinics):
    reply = _ask(
        client,
        two_clinics["patient_a"],
        "How do I change the oil filter on a Toyota Corolla?",
    )

    assert reply["grounded"] is False, reply
    assert reply["reason"] == "no_relevant_sources"
    assert not reply["message"]["citations"]
    assert "don't have" in reply["message"]["content"].lower()


def test_triage_fallback_still_directs_to_care(client, two_clinics):
    """
    Guardrail #2: even with nothing retrieved, triage must not go quiet
    about seeking care.
    """
    reply = _ask(
        client,
        two_clinics["patient_a"],
        "How do I change the oil filter on a Toyota Corolla?",
        mode="triage",
    )

    content = reply["message"]["content"].lower()
    assert reply["grounded"] is False
    assert "urgent" in content or "emergency" in content


# ----------------------------------------------------------------------
# Auth boundaries
# ----------------------------------------------------------------------

def test_patient_cannot_upload_documents(client, two_clinics):
    with open(SOURCE_DIR / "source1.pdf", "rb") as handle:
        response = client.post(
            "/documents/upload",
            headers=_auth(two_clinics["patient_a"]),
            files={"file": ("source1.pdf", handle, "application/pdf")},
            data={"title": "Should not work"},
        )
    assert response.status_code == 403


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/documents").status_code == 401
    assert client.post("/chat/sessions", json={"mode": "general"}).status_code == 401
