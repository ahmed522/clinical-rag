import io
from datetime import datetime, timezone
from types import SimpleNamespace

import chromadb
import fitz
import pytest
from fastapi import HTTPException, UploadFile

import ingest
from app.routers import documents as documents_router
from embed import delete_document_chunks


def _write_text_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Clinical guideline recommendation: monitor HbA1c regularly and "
        "review treatment using the trusted source supplied by the doctor.",
    )
    doc.save(path)
    doc.close()


def test_extract_pdf_records_quality_and_page_provenance(tmp_path):
    pdf_path = tmp_path / "guideline.pdf"
    _write_text_pdf(pdf_path)

    document = ingest.extract_pdf(
        str(pdf_path),
        metadata={"title": "Test guideline", "publisher": "Test publisher"},
    )

    assert document["total_pages"] == 1
    assert document["pages"][0]["page_number"] == 1
    assert document["pages"][0]["extraction_method"] == "native"
    assert document["extraction_report"]["usable"] is True
    assert document["extraction_report"]["text_pages"] == 1
    assert document["extraction_report"]["total_characters"] >= 100


def test_extract_pdf_rejects_empty_searchable_content(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    with pytest.raises(ingest.PDFExtractionError) as exc_info:
        ingest.extract_pdf(str(pdf_path), metadata={"title": "Blank"})

    assert exc_info.value.code == "insufficient_text"
    assert exc_info.value.report["usable"] is False


def test_scanned_page_report_produces_actionable_error():
    document = {
        "total_pages": 1,
        "pages": [
            {
                "page_number": 1,
                "text": "",
                "char_count": 0,
                "image_count": 1,
                "extraction_method": "native",
                "suspected_scanned": True,
            }
        ],
    }

    with pytest.raises(ingest.PDFExtractionError) as exc_info:
        ingest.validate_extraction(document)

    assert exc_info.value.code == "insufficient_text"
    assert "scanned" in str(exc_info.value)


def test_delete_document_chunks_preserves_other_documents(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection("clinic_test")
    collection.add(
        ids=["a-1", "a-2", "b-1"],
        embeddings=[[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
        documents=["a one", "a two", "b one"],
        metadatas=[
            {"document_id": "doc-a"},
            {"document_id": "doc-a"},
            {"document_id": "doc-b"},
        ],
    )

    remaining = delete_document_chunks(
        "doc-a",
        collection_name="clinic_test",
        persist_dir=tmp_path,
    )

    assert remaining == 1
    assert collection.get()["ids"] == ["b-1"]


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.operation = None
        self.payload = None
        self.filters = []

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def _matches(self, row):
        return all(row.get(column) == value for column, value in self.filters)

    def execute(self):
        rows = self.db.rows[self.table]
        if self.operation == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = []
            for payload in payloads:
                row = dict(payload)
                row.setdefault("id", "doc-1" if self.table == "documents" else f"chunk-{len(rows) + 1}")
                row.setdefault("uploaded_at", datetime.now(timezone.utc).isoformat())
                rows.append(row)
                inserted.append(row)
            return _Result(inserted)
        if self.operation == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self.payload)
                    updated.append(dict(row))
            return _Result(updated)
        if self.operation == "delete":
            deleted = [row for row in rows if self._matches(row)]
            self.db.rows[self.table] = [row for row in rows if not self._matches(row)]
            return _Result(deleted)
        return _Result([dict(row) for row in rows if self._matches(row)])


class _Bucket:
    def __init__(self, fail_upload=False):
        self.fail_upload = fail_upload
        self.uploaded = []
        self.removed = []

    def upload(self, path, contents, file_options=None):
        self.uploaded.append(path)
        if self.fail_upload:
            raise RuntimeError("storage unavailable")

    def remove(self, paths):
        self.removed.extend(paths)


class _Storage:
    def __init__(self, bucket):
        self.bucket = bucket

    def from_(self, _name):
        return self.bucket


class _DB:
    def __init__(self, fail_storage=False):
        self.rows = {"documents": [], "chunks": []}
        self.bucket = _Bucket(fail_upload=fail_storage)
        self.storage = _Storage(self.bucket)

    def table(self, name):
        return _Query(self, name)


def _pipeline_stubs(monkeypatch):
    extracted = {
        "total_pages": 1,
        "extraction_report": {
            "usable": True,
            "total_pages": 1,
            "text_pages": 1,
            "total_characters": 200,
            "warnings": [],
        },
        "pages": [{"page_number": 1, "text": "reliable clinical evidence", "char_count": 200}],
    }
    chunks = [
        {
            "chunk_id": "doc-1:p1:c0",
            "text": "reliable clinical evidence",
            "section_title": "General",
            "page_number": 1,
        }
    ]
    monkeypatch.setattr(documents_router, "extract_pdf", lambda *_args, **_kwargs: extracted)
    monkeypatch.setattr(documents_router, "process_document", lambda value: (value, [], []))
    monkeypatch.setattr(documents_router, "chunk_document", lambda *_args, **_kwargs: chunks)
    monkeypatch.setattr(documents_router, "index_chunks", lambda *_args, **_kwargs: 1)


def _upload(db):
    doctor = SimpleNamespace(db=db, clinic_id="clinic-1", user_id="doctor-auth-1")
    file = UploadFile(filename="guideline.pdf", file=io.BytesIO(b"%PDF-1.7\nmock"))
    return documents_router.upload_document(
        file=file,
        title="Trusted guideline",
        publisher="Medical publisher",
        source_url=None,
        topic="General medicine",
        doctor=doctor,
    )


def test_successful_upload_is_ready_but_not_verified(monkeypatch, tmp_path):
    _pipeline_stubs(monkeypatch)
    monkeypatch.setattr(documents_router.settings, "UPLOAD_DIR", tmp_path)
    db = _DB()

    result = _upload(db)

    assert result["status"] == "ready"
    assert result["verified"] is False
    assert result["file_sha256"]
    assert result["extraction_report"]["usable"] is True
    assert db.bucket.uploaded == ["clinic-1/doc-1.pdf"]
    assert not list(tmp_path.rglob("*.pdf"))


def test_failed_upload_cleans_artifacts_and_stays_non_retrievable(monkeypatch, tmp_path):
    _pipeline_stubs(monkeypatch)
    monkeypatch.setattr(documents_router.settings, "UPLOAD_DIR", tmp_path)
    vector_cleanup = []
    monkeypatch.setattr(
        documents_router,
        "delete_document_chunks",
        lambda document_id, collection_name: vector_cleanup.append((document_id, collection_name)),
    )
    db = _DB(fail_storage=True)

    with pytest.raises(HTTPException) as exc_info:
        _upload(db)

    assert exc_info.value.status_code == 422
    assert vector_cleanup == [("doc-1", "clinic_clinic-1")]
    assert db.rows["chunks"] == []
    assert db.rows["documents"][0]["status"] == "failed"
    assert db.rows["documents"][0]["verified"] is False
    assert "storage unavailable" in db.rows["documents"][0]["processing_error"]
    assert db.bucket.removed == ["clinic-1/doc-1.pdf"]
    assert not list(tmp_path.rglob("*.pdf"))
