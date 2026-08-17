"""
Tenant isolation — the safety property the whole SaaS rests on.

A patient's answers must be grounded ONLY in their own clinic's uploaded
documents. If one clinic's guideline can surface in another clinic's
answer, the product is not shippable, so this is tested directly rather
than assumed from the collection naming convention.

Two failure modes are covered:

  1. Cross-tenant retrieval — clinic A's search returning clinic B's text.
  2. Cross-tenant destruction — indexing clinic B wiping clinic A's
     vectors. embed.py used to `shutil.rmtree` the whole persist
     directory to avoid duplicate vectors, which under multi-tenancy
     would delete every other clinic's index. That is a silent, total
     data loss, so it gets its own test.

Run with:
    python -m pytest tests/test_tenant_isolation.py -v
"""

import pytest

from config import collection_name_for
from embed import delete_collection, index_chunks


CLINIC_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
CLINIC_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"

# Deliberately distinctive, non-overlapping vocabulary, so a leak is
# unambiguous rather than a plausible semantic near-miss.
CHUNKS_A = [
    {
        "chunk_id": f"doc-a:p1:c{i}",
        "text": text,
        "section_title": "Cardiology protocol",
        "page_number": 1,
        "source": "clinic_a_cardiology.pdf",
        "title": "Clinic A Cardiology Handbook",
        "publisher": "Clinic A",
        "url": "",
        "topic": "Cardiology",
    }
    for i, text in enumerate([
        "Atrial fibrillation anticoagulation is reviewed at every cardiology visit.",
        "Echocardiography is arranged before any valve replacement referral.",
    ])
]

CHUNKS_B = [
    {
        "chunk_id": f"doc-b:p1:c{i}",
        "text": text,
        "section_title": "Dermatology protocol",
        "page_number": 1,
        "source": "clinic_b_dermatology.pdf",
        "title": "Clinic B Dermatology Handbook",
        "publisher": "Clinic B",
        "url": "",
        "topic": "Dermatology",
    }
    for i, text in enumerate([
        "Psoriasis phototherapy is booked through the dermatology day unit.",
        "Suspicious pigmented lesions are photographed and referred urgently.",
    ])
]


@pytest.fixture(scope="module")
def persist_dir(tmp_path_factory):
    """An isolated Chroma directory, so tests never touch data/chroma_db."""
    return str(tmp_path_factory.mktemp("chroma_isolation"))


@pytest.fixture(scope="module")
def indexed(persist_dir):
    """
    Index both clinics, A first then B.

    Order matters: B is indexed second precisely so that if indexing were
    still destructive, A's vectors would already be gone by assertion time.
    """
    collection_a = collection_name_for(CLINIC_A)
    collection_b = collection_name_for(CLINIC_B)

    delete_collection(collection_a, persist_dir)
    delete_collection(collection_b, persist_dir)

    count_a_before = index_chunks(CHUNKS_A, collection_a, persist_dir)
    count_b = index_chunks(CHUNKS_B, collection_b, persist_dir)

    return {
        "collection_a": collection_a,
        "collection_b": collection_b,
        "count_a_before": count_a_before,
        "count_b": count_b,
    }


def _search(collection_name, persist_dir, query, k=5):
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings

    from config import EMBEDDING_MODEL

    store = Chroma(
        collection_name=collection_name,
        embedding_function=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL),
        persist_directory=persist_dir,
    )
    return store.similarity_search(query, k=k)


def test_each_clinic_gets_its_own_collection():
    assert collection_name_for(CLINIC_A) != collection_name_for(CLINIC_B)
    assert collection_name_for(CLINIC_A) == f"clinic_{CLINIC_A}"


def test_indexing_one_clinic_does_not_destroy_another(indexed, persist_dir):
    """Regression guard for the shutil.rmtree(PERSIST_DIR) behaviour."""
    results = _search(indexed["collection_a"], persist_dir, "anticoagulation review")

    assert results, (
        "Clinic A's vectors disappeared after clinic B was indexed. "
        "Indexing must never delete the shared persist directory."
    )
    assert indexed["count_a_before"] == len(CHUNKS_A)
    assert indexed["count_b"] == len(CHUNKS_B)


def test_clinic_a_never_retrieves_clinic_b_documents(indexed, persist_dir):
    """Ask clinic A a question only clinic B's document can answer."""
    results = _search(
        indexed["collection_a"], persist_dir, "psoriasis phototherapy booking"
    )

    sources = {doc.metadata["source"] for doc in results}
    assert sources == {"clinic_a_cardiology.pdf"}, (
        f"Clinic B content leaked into clinic A retrieval: {sources}"
    )

    joined = " ".join(doc.page_content for doc in results).lower()
    assert "psoriasis" not in joined
    assert "pigmented" not in joined


def test_clinic_b_never_retrieves_clinic_a_documents(indexed, persist_dir):
    """The reverse direction — isolation must not be one-way."""
    results = _search(
        indexed["collection_b"], persist_dir, "atrial fibrillation anticoagulation"
    )

    sources = {doc.metadata["source"] for doc in results}
    assert sources == {"clinic_b_dermatology.pdf"}, (
        f"Clinic A content leaked into clinic B retrieval: {sources}"
    )

    joined = " ".join(doc.page_content for doc in results).lower()
    assert "atrial" not in joined
    assert "echocardiography" not in joined


def test_reindexing_is_idempotent(indexed, persist_dir):
    """
    Deterministic chunk ids mean re-ingesting a document upserts rather
    than appending duplicates — which is what allows indexing to be
    non-destructive in the first place.
    """
    count_again = index_chunks(CHUNKS_A, indexed["collection_a"], persist_dir)

    assert count_again == len(CHUNKS_A), (
        f"Re-indexing duplicated vectors: {count_again} != {len(CHUNKS_A)}"
    )
