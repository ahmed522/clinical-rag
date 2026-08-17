"""
Live walkthrough of the demo success criteria (PRD sec.13).

Seeds two clinics with different guidelines, then shows — against a real
running server — that:

  1. a clinic uploads its own guideline and it is ingested
  2. a patient gets a simplified, CITED answer from that clinic's document
  3. clinic B's document never leaks into clinic A's answers
  4. an out-of-scope question returns the honest fallback, and triage
     still directs to urgent care

Start the server first:
    uvicorn app.main:app --port 8000

Then run:
    python scripts/demo.py

Uses a fresh email per run, so it can be run repeatedly without wiping
the database.
"""

import sys
import time
from pathlib import Path

import httpx

# Clinical text contains characters the default Windows console codepage
# cannot encode (non-breaking hyphens, >=, micro). Printing one raises
# UnicodeEncodeError part-way through the demo.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "data" / "source"

STAMP = str(int(time.time()))
client = httpx.Client(base_url=BASE, timeout=300.0)


def header(text):
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register_clinic(name, specialty):
    response = client.post(
        "/auth/register-clinic",
        json={
            "clinic_name": name,
            "specialty": specialty,
            "admin_email": f"admin-{name.lower().replace(' ', '-')}-{STAMP}@example.com",
            "admin_password": "demo-password-123",
        },
    )
    response.raise_for_status()
    data = response.json()
    print(f"  registered {name:<22} clinic_id={data['clinic_id']}")
    return data


def upload(token, pdf_name, title, publisher):
    path = SOURCE_DIR / pdf_name
    if not path.exists():
        sys.exit(f"Missing {path}. The two guideline PDFs are needed for the demo.")

    print(f"  uploading {pdf_name} ... (extract -> clean -> chunk -> embed)")
    with open(path, "rb") as handle:
        response = client.post(
            "/documents/upload",
            headers=auth(token),
            files={"file": (pdf_name, handle, "application/pdf")},
            data={"title": title, "publisher": publisher},
        )
    response.raise_for_status()
    doc = response.json()
    print(
        f"    -> {doc['page_count']} pages, {doc['chunk_count']} chunks, "
        f"verified={doc['verified']}"
    )
    return doc


def add_patient(admin_token, name):
    email = f"{name.lower()}-{STAMP}@example.com"
    response = client.post(
        "/auth/register-patient",
        headers=auth(admin_token),
        json={"name": name, "email": email, "password": "patient-password-123"},
    )
    response.raise_for_status()

    login = client.post(
        "/auth/login", json={"email": email, "password": "patient-password-123"}
    )
    login.raise_for_status()
    return login.json()["access_token"]


def ask(token, question, mode="general"):
    session = client.post("/chat/sessions", headers=auth(token), json={"mode": mode})
    session.raise_for_status()

    reply = client.post(
        f"/chat/{session.json()['id']}/message",
        headers=auth(token),
        json={"content": question},
    )
    reply.raise_for_status()
    data = reply.json()

    print(f"\n  Q ({mode}): {question}")
    print(f"  grounded: {data['grounded']}" + (f"   reason: {data['reason']}" if data["reason"] else ""))

    answer = data["message"]["content"].replace("\n", "\n     ")
    print(f"  A: {answer}")

    for citation in data["message"]["citations"] or []:
        print(f"     [source] {citation['document']} — page {citation['page']}")

    return data


def main():
    try:
        client.get("/health").raise_for_status()
    except Exception:
        sys.exit(f"No server at {BASE}. Start it with:\n    uvicorn app.main:app --port 8000")

    header("1. Two clinics onboard and upload their OWN guidelines")
    clinic_a = register_clinic("Clinic A", "Endocrinology")
    clinic_b = register_clinic("Clinic B", "Primary Care")

    upload(clinic_a["access_token"], "source1.pdf", "NICE NG28 — Type 2 diabetes in adults", "NICE")
    upload(clinic_b["access_token"], "source2.pdf", "WHO HEARTS-D — Type 2 diabetes", "WHO")

    patient_a = add_patient(clinic_a["access_token"], "Alice")
    patient_b = add_patient(clinic_b["access_token"], "Bob")

    header("2. A patient asks a clinical question — grounded, with citations")
    ask(patient_a, "What is the first-line treatment for type 2 diabetes?")

    header("3. ISOLATION — the same question, answered from each clinic's own document")
    print("  Each answer must cite only that clinic's guideline.")
    a = ask(patient_a, "How should blood glucose be managed?")
    b = ask(patient_b, "How should blood glucose be managed?")

    a_docs = {c["document"] for c in (a["message"]["citations"] or [])}
    b_docs = {c["document"] for c in (b["message"]["citations"] or [])}
    print(f"\n  clinic A cited: {a_docs or '(none)'}")
    print(f"  clinic B cited: {b_docs or '(none)'}")
    print(f"  -> disjoint: {a_docs.isdisjoint(b_docs)}  (no cross-clinic leakage)")

    header("4. SAFETY — out of scope, and triage")
    ask(patient_a, "How do I change the oil filter on a Toyota Corolla?")
    ask(patient_a, "I have crushing chest pain radiating to my arm", mode="triage")

    header("Done")
    print("  Criteria 1-4 demonstrated. Appointments (criterion 5) are not built yet.")
    print("  Answers are composed by the deterministic mock LLM provider:")
    print("  retrieval, citations, isolation and refusal are real; the prose is not.")


if __name__ == "__main__":
    main()
