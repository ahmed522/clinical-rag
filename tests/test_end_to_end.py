"""
End-to-end API tests covering the demo success criteria (PRD sec.13) and
the three-role model's backend-route boundaries.

Exercises the real stack — FastAPI, Supabase Postgres/Auth/Storage (RLS as
the tenant boundary), the ingestion pipeline, local Chroma, and the
generation layer — against the actual Supabase project configured in
.env. There is no mocked database: registration, upload, and chat all hit
the real API, and RLS itself is what proves isolation, not an application
filter standing in for it.

Scope note: this file only exercises requests that actually go through a
FastAPI route (registration, upload/verify, chat). Direct-table RLS for
routes the frontend calls straight from supabase-js with no backend route
at all (patients_select doctor-ownership, doctor_availability, medical
records, appointments) has no HTTP surface for a TestClient to hit — that
was verified live, against the real Supabase project, during development
(see the session's manual RLS-probe testing), not here. A dedicated suite
using app.supabase_client.client_for() directly, the same way the
frontend does, would be the right place to automate that — not this file.

Because this hits real infrastructure, every clinic/user/document/storage
object created by these tests is tracked and deleted in a module-scoped
teardown — this suite must never be the reason test data accumulates in a
real Supabase project.

Criteria covered here:
  #1 a clinic uploads a guideline and it is ingested
  #2 a patient gets a cited answer grounded in that clinic's document
  #3 a second clinic's document does not leak into the first's answers
  #4 an out-of-scope question returns the honest fallback
  #5 an unverified document never grounds a patient answer (guardrail #5)

Run with:
    python -m pytest tests/test_end_to_end.py -v
"""

import os
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "data" / "source"

pytestmark = pytest.mark.skipif(
    not (SOURCE_DIR / "source1.pdf").exists(),
    reason="guideline PDFs not present",
)

# Every clinic_id this module creates, so the module-scoped teardown below
# can find and delete every trace of it regardless of which test or
# fixture created it.
_created_clinic_ids = []


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """
    A TestClient wired to the real Supabase project (.env), with the local
    vector store redirected to a throwaway directory via monkeypatch —
    module-scoped and explicitly undone at teardown, so this never leaks
    into test_tenant_isolation.py if both run in the same pytest session.
    """
    os.environ.setdefault("LLM_PROVIDER", "mock")

    from _pytest.monkeypatch import MonkeyPatch
    from fastapi.testclient import TestClient

    import app.services.retrieval as retrieval
    import rag.embed as embed
    from app.main import app

    chroma_dir = tmp_path_factory.mktemp("e2e_chroma")

    mp = MonkeyPatch()
    mp.setattr(retrieval, "CHROMA_DIR", chroma_dir)
    mp.setattr(embed, "PERSIST_DIR", str(chroma_dir))

    yield TestClient(app)

    mp.undo()


@pytest.fixture(scope="module", autouse=True)
def _cleanup_supabase_test_data():
    """
    Deletes every clinic (and, via cascade, its doctors/documents/chunks/
    patients/appointments/etc.), its auth users, and its storage objects —
    the real-infrastructure cost of this suite hitting the real project.

    Runs regardless of test outcome. Deleting a clinic that never got
    created (a failed setup) is a no-op, not an error.
    """
    yield

    from app.supabase_client import admin_client

    admin = admin_client()

    for clinic_id in _created_clinic_ids:
        try:
            files = admin.storage.from_("guidelines").list(clinic_id)
            paths = [f"{clinic_id}/{f['name']}" for f in files]
            if paths:
                admin.storage.from_("guidelines").remove(paths)
        except Exception:
            pass
        try:
            admin.table("clinics").delete().eq("id", clinic_id).execute()
        except Exception:
            pass

    try:
        users = admin.auth.admin.list_users()
        for user in users:
            if (user.app_metadata or {}).get("clinic_id") in _created_clinic_ids:
                admin.auth.admin.delete_user(user.id)
    except Exception:
        pass

    try:
        import chromadb

        from rag.config import collection_name_for

        chroma_client = chromadb.PersistentClient(
            path=str(PROJECT_ROOT / "data" / "chroma_db")
        )
        # The fixture above redirects CHROMA_DIR to a tmp_path that pytest
        # cleans up on its own; this only matters if a test ever falls
        # back to the real index, which none currently do — cheap insurance.
        for clinic_id in _created_clinic_ids:
            try:
                chroma_client.delete_collection(collection_name_for(clinic_id))
            except Exception:
                pass
    except Exception:
        pass


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


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
    body = response.json()
    _created_clinic_ids.append(body["clinic_id"])
    return body


def _login(client, email, password="demo-password-123"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _register_doctor(client, admin_token, name, email):
    """Admin-only. Registration itself returns no token — login separately."""
    response = client.post(
        "/auth/register-doctor",
        headers=_auth(admin_token),
        json={"name": name, "email": email, "password": "demo-password-123", "specialty": "General"},
    )
    assert response.status_code == 201, response.text
    return _login(client, email)


def _register_patient(client, doctor_token, name, email):
    """Doctor-only — this is what moved off the admin role."""
    response = client.post(
        "/auth/register-patient",
        headers=_auth(doctor_token),
        json={"name": name, "email": email, "password": "demo-password-123"},
    )
    assert response.status_code == 201, response.text
    return _login(client, email)


def _upload(client, doctor_token, pdf_name, title):
    with open(SOURCE_DIR / pdf_name, "rb") as handle:
        response = client.post(
            "/documents/upload",
            headers=_auth(doctor_token),
            files={"file": (pdf_name, handle, "application/pdf")},
            data={"title": title, "publisher": "Test Publisher"},
        )
    assert response.status_code == 201, response.text
    return response.json()


def _verify(client, doctor_token, document_id):
    """Mark a document official, so patients may be answered from it."""
    response = client.patch(
        f"/documents/{document_id}/verify",
        headers=_auth(doctor_token),
        params={"verified": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["verified"] is True
    return response.json()


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
    """
    Clinic A holds the NICE guideline, clinic B holds the WHO one.

    Per the three-role model: the admin registers only the clinic and its
    doctor; the doctor uploads/verifies the document and registers the
    patient. Both documents are verified, which is the normal state for a
    document in use — the unverified case is covered separately by
    test_unverified_document_is_never_used_in_answers.

    Emails are unique per test run (not just per module) — Supabase Auth
    treats them as globally unique, and a prior interrupted run's teardown
    failing would otherwise break every subsequent run.
    """
    suffix = str(int(time.time() * 1000))

    a = _register_clinic(client, "Test Clinic A", f"admin-a-{suffix}@example.com")
    b = _register_clinic(client, "Test Clinic B", f"admin-b-{suffix}@example.com")

    doctor_a = _register_doctor(client, a["access_token"], "Dr. A", f"doctor-a-{suffix}@example.com")
    doctor_b = _register_doctor(client, b["access_token"], "Dr. B", f"doctor-b-{suffix}@example.com")

    doc_a = _upload(client, doctor_a, "source1.pdf", "NICE NG28 Type 2 Diabetes")
    doc_b = _upload(client, doctor_b, "source2.pdf", "WHO HEARTS-D Diabetes")

    _verify(client, doctor_a, doc_a["id"])
    _verify(client, doctor_b, doc_b["id"])

    return {
        "a": a,
        "b": b,
        "doctor_a": doctor_a,
        "doctor_b": doctor_b,
        "patient_a": _register_patient(client, doctor_a, "Alice", f"alice-{suffix}@example.com"),
        "patient_b": _register_patient(client, doctor_b, "Bob", f"bob-{suffix}@example.com"),
    }


# ----------------------------------------------------------------------
# Criterion #1 — upload and ingestion
# ----------------------------------------------------------------------

def test_upload_ingests_and_scopes_to_clinic(client, two_clinics):
    response = client.get("/documents", headers=_auth(two_clinics["doctor_a"]))
    assert response.status_code == 200

    documents = response.json()
    assert len(documents) == 1, "clinic A should see only its own document"
    assert documents[0]["chunk_count"] > 0
    assert documents[0]["page_count"] > 0
    # This fixture verified its documents, since that is their state in
    # normal use. That uploads ARRIVE unverified is asserted in
    # test_unverified_document_is_never_used_in_answers.
    assert documents[0]["verified"] is True


def test_clinic_cannot_see_another_clinics_documents(client, two_clinics):
    """
    RLS's documents_select policy, exercised through the real API — not a
    mocked filter standing in for it.
    """
    a_docs = client.get("/documents", headers=_auth(two_clinics["doctor_a"])).json()
    b_docs = client.get("/documents", headers=_auth(two_clinics["doctor_b"])).json()

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
    """
    RLS's sessions_select policy: a session belongs to the patient who had
    it, not merely to the clinic it happened in.
    """
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
# Guardrail #5 — unverified sources stay out of patient answers
# ----------------------------------------------------------------------

def test_unverified_document_is_never_used_in_answers(client):
    """
    A doctor uploads a guideline but has not yet confirmed it is official.
    Until it does, patients must get the honest fallback rather than an
    answer grounded in an unconfirmed source — then the same question must
    succeed once the document is verified.

    This is enforced twice, independently — RLS's documents_select policy
    hides the unverified row from the patient's own client entirely, and
    retrieval separately restricts the vector search to verified document
    ids — and this test exercises the real path through both, not either
    one in isolation.

    Uses its own clinic so the before/after is unambiguous: with no other
    documents in the tenant, a grounded answer can only have come from
    this one.
    """
    suffix = str(int(time.time() * 1000))
    clinic = _register_clinic(client, "Test Clinic C", f"admin-c-{suffix}@example.com")
    doctor = _register_doctor(client, clinic["access_token"], "Dr. C", f"doctor-c-{suffix}@example.com")

    document = _upload(client, doctor, "source2.pdf", "WHO HEARTS-D Diabetes")
    assert document["verified"] is False, "uploads must arrive unverified"

    patient = _register_patient(client, doctor, "Carol", f"carol-{suffix}@example.com")
    question = "How is type 2 diabetes diagnosed?"

    before = _ask(client, patient, question)
    assert before["grounded"] is False, (
        "an unverified document must not ground a patient answer",
        before,
    )
    assert not before["message"]["citations"]

    _verify(client, doctor, document["id"])

    after = _ask(client, patient, question)
    assert after["grounded"] is True, ("verifying should make it usable", after)
    assert after["message"]["citations"], "a grounded answer must carry citations"


# ----------------------------------------------------------------------
# Role boundaries — three roles, not two
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


def test_admin_cannot_upload_documents(client, two_clinics):
    """
    The core scope change: admin is administrative only, not medical.
    Uploading (and, by the same authority, verifying) moved to the doctor
    role entirely — this is the FastAPI-level guard; RLS's
    documents_doctor_write policy is the independent real enforcement,
    verified live during development against the actual project.
    """
    with open(SOURCE_DIR / "source1.pdf", "rb") as handle:
        response = client.post(
            "/documents/upload",
            headers=_auth(two_clinics["a"]["access_token"]),
            files={"file": ("source1.pdf", handle, "application/pdf")},
            data={"title": "Should not work"},
        )
    assert response.status_code == 403


def test_admin_cannot_register_patients(client, two_clinics):
    """Patient registration moved from admin to doctor — admin no longer holds this route at all."""
    response = client.post(
        "/auth/register-patient",
        headers=_auth(two_clinics["a"]["access_token"]),
        json={"name": "Should not work", "email": "shouldnotwork@example.com", "password": "demo-password-123"},
    )
    assert response.status_code == 403


def test_doctor_cannot_register_doctors(client, two_clinics):
    """register-doctor stays admin-only — a doctor cannot mint peer accounts."""
    response = client.post(
        "/auth/register-doctor",
        headers=_auth(two_clinics["doctor_a"]),
        json={"name": "Should not work", "email": "shouldnotwork2@example.com", "password": "demo-password-123", "specialty": "General"},
    )
    assert response.status_code == 403


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/documents").status_code == 401
    assert client.post("/chat/sessions", json={"mode": "general"}).status_code == 401


def test_clinic_slug_is_publicly_resolvable(client, two_clinics):
    """
    The one deliberately public read (app/routers/clinics.py) — the
    /clinic/{slug} frontend page needs this before the visitor has
    authenticated at all, so this call carries no Authorization header,
    unlike every other request in this file.
    """
    admin_a = two_clinics["a"]

    from app.supabase_client import admin_client

    clinic_row = (
        admin_client().table("clinics").select("slug").eq("id", admin_a["clinic_id"]).single().execute().data
    )

    response = client.get(f"/clinics/by-slug/{clinic_row['slug']}")
    assert response.status_code == 200
    assert response.json()["id"] == admin_a["clinic_id"]

    assert client.get("/clinics/by-slug/no-such-clinic-slug").status_code == 404
