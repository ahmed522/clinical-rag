"""Run a 20-question, product-level Clinical RAG acceptance test.

Unlike the offline evaluators, this script exercises the same HTTP path as the
web application:

    clinic registration -> role login -> doctor registration -> PDF upload
    -> extraction/chunking/indexing -> trusted-source verification -> doctor
    chat session -> retrieval/reranking -> generation
    -> evidence verification -> persistence/history

The running API's configured LLM provider is used.  The script never changes
``LLM_PROVIDER``.  It writes a lossless JSON report and a readable Markdown
report containing every question, answer, citation, score, check, retrieval
result, and stage latency.

Run from the project root while FastAPI is listening on port 8000:

    .\.venv\Scripts\python.exe -m scripts.test_full_rag

Temporary Supabase/Auth/Storage/Chroma data is deleted by default.  Pass
``--keep-data`` only when you intentionally want to inspect the test tenant.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Optional

import httpx

from app.config import settings
from app.llm import get_provider
from app.llm_prompts import PROMPT_VERSION
from rag.config import (
    ABSURD_DISTANCE,
    CHROMA_DIR,
    EMBEDDING_MODEL,
    RERANK_CANDIDATE_K,
    RERANK_ENABLED,
    RERANK_MODEL,
    RETRIEVAL_K,
    collection_name_for,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "data" / "source"
DATASET_PATH = PROJECT_ROOT / "evaluation" / "clinical_queries.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "full_rag_runs"
EXTERNAL_LLM_PROVIDERS = {"anthropic", "groq", "openai", "openrouter"}

# Representative corpus coverage plus the three most important negative cases.
# The IDs come from evaluation/clinical_queries.json and remain visible in the
# report, so changing the evaluation set never silently changes this benchmark.
DEFAULT_QUESTION_IDS = [
    1, 3, 6, 7, 9, 12, 13, 14, 15, 18, 19, 23,
    27, 29, 31, 32, 35,
    104, 105, 106,
]

SOURCE_SPECS = {
    "source1.pdf": {
        "title": "Type 2 diabetes in adults: management (NG28)",
        "publisher": "National Institute for Health and Care Excellence (NICE)",
        "source_url": "https://www.nice.org.uk/guidance/ng28",
        "topic": "Type 2 Diabetes",
    },
    "source2.pdf": {
        "title": "HEARTS D: Diagnosis and management of type 2 diabetes",
        "publisher": "World Health Organization (WHO)",
        "source_url": "https://iris.who.int/handle/10665/331710",
        "topic": "Type 2 Diabetes",
    },
}

DEPENDENCY_FAILURE_REASONS = {
    "retrieval_unavailable",
    "generation_unavailable",
    "generation_rate_limited",
    "evidence_verifier_disabled",
    "evidence_verification_unavailable",
    "evidence_verification_rate_limited",
}

REQUIRED_CITATION_FIELDS = (
    "id",
    "source_id",
    "rank",
    "document",
    "document_id",
    "page",
    "section",
    "chunk_id",
    "excerpt",
)


class FullRagTestError(RuntimeError):
    """A setup or API-contract error that makes the run invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _percent(numerator: int | float, denominator: int | float) -> Optional[float]:
    if not denominator:
        return None
    return round(100.0 * float(numerator) / float(denominator), 2)


def _mean(values: Iterable[float]) -> Optional[float]:
    clean = [float(value) for value in values if value is not None]
    return round(statistics.fmean(clean), 4) if clean else None


def _percentile(values: Iterable[float], percentile: float) -> Optional[float]:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return round(clean[0], 2)
    position = (len(clean) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(clean[lower], 2)
    value = clean[lower] + (clean[upper] - clean[lower]) * (position - lower)
    return round(value, 2)


def _matches_any(patterns: list[str], value: str) -> bool:
    if not patterns:
        return True
    for pattern in patterns:
        try:
            if re.search(pattern, value or "", re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in (value or "").lower():
                return True
    return False


def _load_questions(ids: list[int]) -> list[dict[str, Any]]:
    if not DATASET_PATH.exists():
        raise FullRagTestError(f"Labelled dataset is missing: {DATASET_PATH}")
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    by_id = {int(row["id"]): row for row in payload.get("queries", [])}
    missing = [question_id for question_id in ids if question_id not in by_id]
    if missing:
        raise FullRagTestError(f"Question IDs are missing from the dataset: {missing}")
    return [by_id[question_id] for question_id in ids]


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: tuple[int, ...] = (200,),
    **kwargs: Any,
) -> Any:
    started = perf_counter()
    try:
        response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise FullRagTestError(f"{method} {path} could not reach the API: {exc}") from exc
    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    if response.status_code not in expected:
        body = response.text[:2000]
        raise FullRagTestError(
            f"{method} {path} returned HTTP {response.status_code} in {elapsed_ms} ms: {body}"
        )
    try:
        return response.json(), elapsed_ms
    except ValueError as exc:
        raise FullRagTestError(f"{method} {path} returned non-JSON content") from exc


def _record_step(steps: list[dict[str, Any]], name: str, elapsed_ms: float, **details: Any) -> None:
    steps.append({"step": name, "ok": True, "latency_ms": elapsed_ms, **details})
    print(f"[setup] {name:<28} OK  {elapsed_ms:>9.2f} ms", flush=True)


def _setup_product_flow(client: httpx.Client, run_id: str) -> dict[str, Any]:
    password = f"Rag-Eval-{uuid.uuid4().hex[:10]}!"
    suffix = run_id.lower().replace("_", "-")
    admin_email = f"rag-eval-admin-{suffix}@example.com"
    doctor_email = f"rag-eval-doctor-{suffix}@example.com"
    patient_email = f"rag-eval-patient-{suffix}@example.com"
    steps: list[dict[str, Any]] = []

    health, elapsed = _request_json(client, "GET", "/health")
    if health.get("status") != "ok":
        raise FullRagTestError(f"Unexpected health response: {health}")
    _record_step(steps, "API health", elapsed)

    clinic, elapsed = _request_json(
        client,
        "POST",
        "/auth/register-clinic",
        expected=(201,),
        json={
            "clinic_name": f"Clinical RAG Evaluation {run_id}",
            "specialty": "Endocrinology",
            "admin_email": admin_email,
            "admin_password": password,
        },
    )
    clinic_id = clinic["clinic_id"]
    _record_step(steps, "Clinic registration", elapsed, clinic_id=clinic_id)

    admin_login, elapsed = _request_json(
        client,
        "POST",
        "/auth/login",
        json={"email": admin_email, "password": password},
    )
    if admin_login.get("role") != "clinic_admin" or admin_login.get("clinic_id") != clinic_id:
        raise FullRagTestError(f"Clinic admin login returned wrong tenant/role: {admin_login}")
    admin_token = admin_login["access_token"]
    _record_step(steps, "Clinic admin login", elapsed, role=admin_login.get("role"))

    doctor, elapsed = _request_json(
        client,
        "POST",
        "/auth/register-doctor",
        expected=(201,),
        headers=_auth(admin_token),
        json={
            "name": "RAG Evaluation Doctor",
            "email": doctor_email,
            "password": password,
            "specialty": "Endocrinology",
        },
    )
    _record_step(steps, "Doctor registration", elapsed, doctor_id=doctor.get("doctor_id"))

    doctor_login, elapsed = _request_json(
        client,
        "POST",
        "/auth/login",
        json={"email": doctor_email, "password": password},
    )
    if doctor_login.get("role") != "doctor" or doctor_login.get("clinic_id") != clinic_id:
        raise FullRagTestError(f"Doctor login returned wrong tenant/role: {doctor_login}")
    doctor_token = doctor_login["access_token"]
    _record_step(steps, "Doctor login", elapsed, role=doctor_login.get("role"))

    doctor_session, elapsed = _request_json(
        client,
        "POST",
        "/doctor/chat/sessions",
        expected=(201,),
        headers=_auth(doctor_token),
    )
    _record_step(steps, "Doctor chat session", elapsed, session_id=doctor_session.get("id"))

    documents: dict[str, dict[str, Any]] = {}
    for filename, metadata in SOURCE_SPECS.items():
        pdf_path = SOURCE_DIR / filename
        if not pdf_path.exists():
            raise FullRagTestError(f"Required evaluation PDF is missing: {pdf_path}")
        with pdf_path.open("rb") as handle:
            uploaded, elapsed = _request_json(
                client,
                "POST",
                "/documents/upload",
                expected=(201,),
                headers=_auth(doctor_token),
                files={"file": (filename, handle, "application/pdf")},
                data=metadata,
            )
        if uploaded.get("status") != "ready" or not uploaded.get("chunk_count"):
            raise FullRagTestError(f"{filename} did not finish ingestion: {uploaded}")
        _record_step(
            steps,
            f"Ingest {filename}",
            elapsed,
            document_id=uploaded.get("id"),
            pages=uploaded.get("page_count"),
            chunks=uploaded.get("chunk_count"),
            extraction_report=uploaded.get("extraction_report"),
        )

        verified, verify_elapsed = _request_json(
            client,
            "PATCH",
            f"/documents/{uploaded['id']}/verify",
            headers=_auth(doctor_token),
            params={"verified": "true"},
        )
        if not verified.get("verified"):
            raise FullRagTestError(f"{filename} was not marked trusted: {verified}")
        _record_step(steps, f"Verify {filename}", verify_elapsed, verified=True)
        documents[filename] = {
            "id": uploaded["id"],
            "title": uploaded.get("title"),
            "publisher": uploaded.get("publisher"),
            "source_url": uploaded.get("source_url"),
            "page_count": uploaded.get("page_count"),
            "chunk_count": uploaded.get("chunk_count"),
            "verified": verified.get("verified"),
        }

    patient, elapsed = _request_json(
        client,
        "POST",
        "/auth/register-patient",
        expected=(201,),
        # Patient registration is an administrative workflow. The doctor
        # token is retained for the independent doctor-chat smoke checks;
        # this request must exercise the same clinic-admin route as the UI.
        headers=_auth(admin_token),
        json={
            "name": "RAG Evaluation Patient",
            "email": patient_email,
            "password": password,
            "age": 45,
            "phone": "+200000000000",
        },
    )
    _record_step(steps, "Patient registration", elapsed, patient_id=patient.get("patient_id"))

    patient_login, elapsed = _request_json(
        client,
        "POST",
        "/auth/login",
        json={"email": patient_email, "password": password},
    )
    if patient_login.get("role") != "patient" or patient_login.get("clinic_id") != clinic_id:
        raise FullRagTestError(f"Patient login returned wrong tenant/role: {patient_login}")
    patient_token = patient_login["access_token"]
    _record_step(steps, "Patient login", elapsed, role=patient_login.get("role"))

    session, elapsed = _request_json(
        client,
        "POST",
        "/chat/sessions",
        expected=(201,),
        headers=_auth(patient_token),
        json={"mode": "general"},
    )
    _record_step(steps, "Patient chat session", elapsed, session_id=session.get("id"))

    return {
        "clinic_id": clinic_id,
        "doctor_id": doctor.get("doctor_id"),
        "doctor_token": doctor_token,
        "doctor_session_id": doctor_session["id"],
        "patient_id": patient.get("patient_id"),
        "patient_token": patient_token,
        "session_id": session["id"],
        "documents": documents,
        "steps": steps,
        # User IDs and bearer tokens are intentionally omitted. Cleanup resolves them by exact
        # clinic_id, and the report never contains credentials or bearer tokens.
    }


def _load_chunk_lookup(document_ids: list[str]) -> tuple[dict[str, dict[str, Any]], Optional[str]]:
    """Load answer-bearing text for labelled retrieval metrics, not generation."""
    try:
        from app.supabase_client import admin_client

        rows = (
            admin_client()
            .table("chunks")
            .select("document_id,content,page_number,section_title,vector_ref")
            .in_("document_id", document_ids)
            .execute()
            .data
        )
        return {
            str(row.get("vector_ref")): row
            for row in rows
            if row.get("vector_ref")
        }, None
    except Exception as exc:  # metrics degrade, the product path still runs
        return {}, f"Could not load chunk text for answer@k scoring: {type(exc).__name__}: {exc}"


def _retrieval_metrics(
    query: dict[str, Any],
    retrieved: list[dict[str, Any]],
    chunk_lookup: dict[str, dict[str, Any]],
    expected_document_id: Optional[str],
) -> Optional[dict[str, Any]]:
    if query.get("scope") != "in_scope":
        return None

    expected_pages = {int(page) for page in query.get("expected_pages") or []}
    patterns = query.get("must_contain") or []
    page_hits: list[bool] = []
    answer_hits: list[bool] = []
    enriched: list[dict[str, Any]] = []

    for item in retrieved:
        page = item.get("page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        page_hit = bool(
            expected_document_id
            and item.get("document_id") == expected_document_id
            and page in expected_pages
        )
        chunk = chunk_lookup.get(str(item.get("chunk_id")), {})
        content = str(chunk.get("content") or "")
        answer_hit = page_hit and bool(content) and _matches_any(patterns, content)
        page_hits.append(page_hit)
        answer_hits.append(answer_hit)
        enriched.append({**item, "labelled_page_hit": page_hit, "labelled_answer_hit": answer_hit})

    first_answer = next((index for index, hit in enumerate(answer_hits, start=1) if hit), None)
    return {
        "recall_at_1": any(page_hits[:1]),
        "recall_at_3": any(page_hits[:3]),
        "recall_at_5": any(page_hits[:5]),
        "answer_at_1": any(answer_hits[:1]),
        "answer_at_3": any(answer_hits[:3]),
        "answer_at_5": any(answer_hits[:5]),
        "context_precision": round(sum(answer_hits) / len(answer_hits), 4) if answer_hits else 0.0,
        "reciprocal_rank": round(1 / first_answer, 4) if first_answer else 0.0,
        "retrieved": enriched,
    }


def _citation_matches_expected(
    citation: dict[str, Any], expected_document_id: Optional[str], expected_pages: set[int]
) -> bool:
    try:
        page = int(citation.get("page"))
    except (TypeError, ValueError):
        return False
    return bool(expected_document_id and citation.get("document_id") == expected_document_id and page in expected_pages)


def _score_reply(
    query: dict[str, Any],
    reply: dict[str, Any],
    elapsed_ms: float,
    documents: dict[str, dict[str, Any]],
    chunk_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    # Patient responses wrap the persisted message in {message: ...}; doctor
    # responses are the persisted message itself. The evaluator intentionally
    # supports both shapes, but its clinical benchmark always uses the doctor
    # route because patients are non-medical by product policy.
    message = reply.get("message") if isinstance(reply.get("message"), dict) else reply
    evidence = message.get("evidence") or {}
    checks = evidence.get("checks") or {}
    audit = message.get("rag_metadata") or {}
    citations = message.get("citations") or []
    retrieved = list(audit.get("retrieved") or [])
    grounded = bool(reply.get("grounded", message.get("grounded", False)))
    reason = reply.get("reason") or message.get("reason")
    answer = str(message.get("content") or "")
    expected_source = query.get("expected_source")
    expected_document_id = (documents.get(expected_source) or {}).get("id")
    expected_pages = {int(page) for page in query.get("expected_pages") or []}

    citation_valid = None
    citation_exact = None
    citation_page_correct = None
    citation_answer_support = None
    citation_coverage = float(checks.get("citation_coverage") or 0.0)
    verifier_passed = bool(checks.get("verifier_passed"))
    safety_passed = bool(checks.get("safety_passed"))

    if grounded:
        citation_ids = [citation.get("id") for citation in citations]
        source_ids = [citation.get("source_id") for citation in citations]
        citation_valid = bool(citations) and all(
            all(citation.get(field) not in (None, "") for field in REQUIRED_CITATION_FIELDS)
            and isinstance(citation.get("source_id"), int)
            and 1 <= citation.get("source_id") <= len(retrieved or citations)
            for citation in citations
        ) and len(citation_ids) == len(set(citation_ids)) and len(source_ids) == len(set(source_ids))
        citation_exact = bool(checks.get("exact_excerpts_passed"))
        citation_page_correct = any(
            _citation_matches_expected(citation, expected_document_id, expected_pages)
            for citation in citations
        ) if expected_document_id else False
        patterns = query.get("must_contain") or []
        citation_answer_support = any(
            _citation_matches_expected(citation, expected_document_id, expected_pages)
            and _matches_any(patterns, str(citation.get("excerpt") or ""))
            for citation in citations
        ) if expected_document_id else False

    faithfulness_passed = bool(
        grounded
        and citation_valid
        and citation_exact
        and citation_coverage == 1.0
        and checks.get("evidence_match_passed")
        and verifier_passed
        and safety_passed
    )
    correct_abstention = query.get("scope") == "out_of_scope" and not grounded
    dependency_failure = reason in DEPENDENCY_FAILURE_REASONS
    expected_safety_reason = (
        "patient_specific_dosage_or_treatment" if int(query["id"]) == 105 else None
    )
    safety_refusal_correct = (
        reason == expected_safety_reason if expected_safety_reason else None
    )

    retrieval = _retrieval_metrics(
        query, retrieved, chunk_lookup, expected_document_id
    )

    if query.get("scope") == "in_scope":
        components = {
            "http_response": 10,
            "grounded_answer": 20 if grounded else 0,
            "valid_citations": 15 if citation_valid else 0,
            "exact_excerpts": 15 if citation_exact else 0,
            "full_citation_coverage": 10 if citation_coverage == 1.0 else 0,
            "semantic_verifier": 10 if verifier_passed else 0,
            "expected_page": 10 if citation_page_correct else 0,
            "answer_bearing_evidence": 10 if citation_answer_support else 0,
        }
        passed = bool(sum(components.values()) == 100)
    else:
        reason_quality = bool(correct_abstention and not dependency_failure)
        final_guardrail = (
            safety_refusal_correct if expected_safety_reason else reason_quality
        )
        components = {
            "http_response": 10,
            "correct_abstention": 50 if correct_abstention else 0,
            "insufficient_evidence_label": 20 if evidence.get("evidence_strength") == "insufficient" else 0,
            "no_false_citations": 10 if not citations else 0,
            "correct_refusal_reason": 10 if final_guardrail else 0,
        }
        passed = bool(sum(components.values()) == 100)

    verification_rows = list(audit.get("verification") or [])
    unsupported_claims = sum(1 for row in verification_rows if not row.get("supported", False))
    overconfident_claims = sum(1 for row in verification_rows if row.get("overconfident", False))

    return {
        "id": query["id"],
        "query": query["query"],
        "category": query.get("category"),
        "scope": query.get("scope"),
        "expected": {
            "source": expected_source,
            "document_id": expected_document_id,
            "pages": query.get("expected_pages") or [],
            "recommendation": query.get("expected_recommendation"),
            "must_contain": query.get("must_contain") or [],
            "why": query.get("why"),
        },
        "score": sum(components.values()),
        "score_components": components,
        "passed": passed,
        "grounded": grounded,
        "reason": reason,
        "dependency_failure": dependency_failure,
        "answer": answer,
        "evidence_strength": evidence.get("evidence_strength") or message.get("evidence_strength"),
        "evidence_checks": checks,
        "recommendation_claims": evidence.get("recommendation_claims") or [],
        "supporting_evidence": evidence.get("supporting_evidence") or [],
        "safety_notice": evidence.get("safety_notice"),
        "evidence_checked": evidence.get("evidence_checked") or [],
        "missing_evidence": evidence.get("missing_evidence"),
        "citations": citations,
        "citation_valid": citation_valid,
        "citation_exact": citation_exact,
        "citation_page_correct": citation_page_correct,
        "citation_answer_support": citation_answer_support,
        "citation_coverage": citation_coverage,
        "verifier_passed": verifier_passed,
        "safety_passed": safety_passed,
        "faithfulness_passed": faithfulness_passed,
        "correct_abstention": correct_abstention,
        "safety_refusal_correct": safety_refusal_correct,
        "unsupported_claims": unsupported_claims,
        "overconfident_claims": overconfident_claims,
        "retrieval_metrics": retrieval,
        "retrieved": (retrieval or {}).get("retrieved", retrieved),
        "provider": audit.get("provider"),
        "model": audit.get("model"),
        "prompt_version": message.get("prompt_version") or audit.get("prompt_version"),
        "validation_errors": audit.get("validation_errors") or [],
        "verification": verification_rows,
        "stage_latency_ms": audit.get("latency_ms") or {},
        "http_round_trip_ms": elapsed_ms,
        # Preserve the exact contract for later debugging and regression diffs.
        "raw_response": reply,
    }


def _error_result(query: dict[str, Any], error: Exception, elapsed_ms: float) -> dict[str, Any]:
    return {
        "id": query["id"],
        "query": query["query"],
        "category": query.get("category"),
        "scope": query.get("scope"),
        "score": 0,
        "score_components": {},
        "passed": False,
        "grounded": False,
        "reason": "api_error",
        "dependency_failure": True,
        "answer": "",
        "citations": [],
        "citation_valid": None,
        "citation_exact": None,
        "citation_page_correct": None,
        "citation_answer_support": None,
        "citation_coverage": 0.0,
        "verifier_passed": False,
        "safety_passed": False,
        "faithfulness_passed": False,
        "correct_abstention": False,
        "safety_refusal_correct": False if int(query["id"]) == 105 else None,
        "unsupported_claims": 0,
        "overconfident_claims": 0,
        "retrieval_metrics": None,
        "retrieved": [],
        "stage_latency_ms": {},
        "http_round_trip_ms": elapsed_ms,
        "error": f"{type(error).__name__}: {error}",
    }


def _ask_questions(
    client: httpx.Client,
    setup: dict[str, Any],
    questions: list[dict[str, Any]],
    chunk_lookup: dict[str, dict[str, Any]],
    delay_seconds: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    endpoint = f"/doctor/chat/{setup['doctor_session_id']}/message"
    headers = _auth(setup["doctor_token"])

    for index, query in enumerate(questions, start=1):
        print(f"\n[{index:02d}/{len(questions):02d}] Q{query['id']}: {query['query']}", flush=True)
        started = perf_counter()
        try:
            reply, elapsed = _request_json(
                client,
                "POST",
                endpoint,
                headers=headers,
                json={"content": query["query"]},
            )
            result = _score_reply(query, reply, elapsed, setup["documents"], chunk_lookup)
        except Exception as exc:
            elapsed = round((perf_counter() - started) * 1000, 2)
            result = _error_result(query, exc, elapsed)

        results.append(result)
        status = "PASS" if result["passed"] else "CHECK"
        print(
            f"[{status}] score={result['score']:>3}/100  grounded={result['grounded']}  "
            f"strength={result.get('evidence_strength') or '-'}  reason={result.get('reason') or '-'}",
            flush=True,
        )
        print(f"Answer: {result.get('answer') or '[no answer returned]'}", flush=True)
        for citation in result.get("citations") or []:
            print(
                "  Citation "
                f"{citation.get('id')}: {citation.get('document')} p.{citation.get('page')} "
                f"chunk={citation.get('chunk_id')} vector={citation.get('vector_distance')} "
                f"rerank={citation.get('rerank_score')}",
                flush=True,
            )
        if result.get("error"):
            print(f"  ERROR: {result['error']}", flush=True)
        if delay_seconds and index < len(questions):
            time.sleep(delay_seconds)

    return results


def _summarize(results: list[dict[str, Any]], history_count: Optional[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    in_scope = [result for result in results if result.get("scope") == "in_scope"]
    out_scope = [result for result in results if result.get("scope") == "out_of_scope"]
    grounded = [result for result in results if result.get("grounded")]
    retrieval_rows = [result["retrieval_metrics"] for result in in_scope if result.get("retrieval_metrics")]
    stage_names = ("retrieval", "generation", "verification", "total")

    latency: dict[str, Any] = {
        "http_round_trip_p50": _percentile(
            [result.get("http_round_trip_ms") for result in results], 0.50
        ),
        "http_round_trip_p95": _percentile(
            [result.get("http_round_trip_ms") for result in results], 0.95
        ),
    }
    for stage in stage_names:
        values = [
            (result.get("stage_latency_ms") or {}).get(stage)
            for result in results
            if (result.get("stage_latency_ms") or {}).get(stage) is not None
        ]
        latency[f"{stage}_mean"] = _mean(values)
        latency[f"{stage}_p50"] = _percentile(values, 0.50)
        latency[f"{stage}_p95"] = _percentile(values, 0.95)

    failure_reasons = Counter(
        result.get("reason") or "grounded"
        for result in results
        if not result.get("passed")
    )
    providers = sorted({result.get("provider") for result in results if result.get("provider")})
    models = sorted({result.get("model") for result in results if result.get("model")})

    summary = {
        "questions": {
            "total": len(results),
            "passed": sum(bool(result.get("passed")) for result in results),
            "mean_score": _mean([result.get("score", 0) for result in results]),
            "api_errors": sum(bool(result.get("error")) for result in results),
        },
        "in_scope": {
            "total": len(in_scope),
            "grounded_answers": sum(bool(result.get("grounded")) for result in in_scope),
            "grounded_rate_percent": _percent(
                sum(bool(result.get("grounded")) for result in in_scope), len(in_scope)
            ),
            "correct_page_citations": sum(bool(result.get("citation_page_correct")) for result in in_scope),
            "answer_bearing_citations": sum(bool(result.get("citation_answer_support")) for result in in_scope),
            "strict_passes": sum(bool(result.get("passed")) for result in in_scope),
        },
        "out_of_scope": {
            "total": len(out_scope),
            "correct_abstentions": sum(bool(result.get("correct_abstention")) for result in out_scope),
            "abstention_rate_percent": _percent(
                sum(bool(result.get("correct_abstention")) for result in out_scope), len(out_scope)
            ),
            "patient_specific_safety_pass": any(
                result.get("safety_refusal_correct") is True for result in out_scope
            ),
        },
        "retrieval": {
            "recall_at_1_percent": _percent(sum(bool(row.get("recall_at_1")) for row in retrieval_rows), len(retrieval_rows)),
            "recall_at_3_percent": _percent(sum(bool(row.get("recall_at_3")) for row in retrieval_rows), len(retrieval_rows)),
            "recall_at_5_percent": _percent(sum(bool(row.get("recall_at_5")) for row in retrieval_rows), len(retrieval_rows)),
            "answer_at_1_percent": _percent(sum(bool(row.get("answer_at_1")) for row in retrieval_rows), len(retrieval_rows)),
            "answer_at_3_percent": _percent(sum(bool(row.get("answer_at_3")) for row in retrieval_rows), len(retrieval_rows)),
            "answer_at_5_percent": _percent(sum(bool(row.get("answer_at_5")) for row in retrieval_rows), len(retrieval_rows)),
            "mean_context_precision": _mean([row.get("context_precision") for row in retrieval_rows]),
            "mrr": _mean([row.get("reciprocal_rank") for row in retrieval_rows]),
        },
        "grounding": {
            "displayed_grounded_answers": len(grounded),
            "valid_citations": sum(result.get("citation_valid") is True for result in grounded),
            "exact_excerpts": sum(result.get("citation_exact") is True for result in grounded),
            "full_citation_coverage": sum(result.get("citation_coverage") == 1.0 for result in grounded),
            "verifier_passes": sum(bool(result.get("verifier_passed")) for result in grounded),
            "faithfulness_passes": sum(bool(result.get("faithfulness_passed")) for result in grounded),
            "unsupported_claims": sum(int(result.get("unsupported_claims") or 0) for result in results),
            "overconfident_claims": sum(int(result.get("overconfident_claims") or 0) for result in results),
            "evidence_strength": dict(Counter(result.get("evidence_strength") or "missing" for result in results)),
        },
        "persistence": {
            "expected_messages": len(results) * 2,
            "persisted_messages": history_count,
            "history_complete": history_count == len(results) * 2 if history_count is not None else False,
        },
        "runtime": {
            "providers_seen": providers,
            "models_seen": models,
            "latency_ms": latency,
        },
        "failure_reasons": dict(failure_reasons),
    }

    has_out_of_scope = bool(out_scope)
    has_dosage_safety_case = any(
        result.get("safety_refusal_correct") is not None for result in results
    )
    gates = {
        "no_api_errors": {
            "passed": summary["questions"]["api_errors"] == 0,
            "actual": summary["questions"]["api_errors"],
            "target": 0,
        },
        "citation_integrity_100_percent": {
            "passed": all(result.get("citation_valid") is True for result in grounded),
            "actual": _percent(summary["grounding"]["valid_citations"], len(grounded)),
            "target": 100.0,
        },
        "exact_excerpt_100_percent": {
            "passed": all(result.get("citation_exact") is True for result in grounded),
            "actual": _percent(summary["grounding"]["exact_excerpts"], len(grounded)),
            "target": 100.0,
        },
        "citation_coverage_100_percent": {
            "passed": all(result.get("citation_coverage") == 1.0 for result in grounded),
            "actual": _percent(summary["grounding"]["full_citation_coverage"], len(grounded)),
            "target": 100.0,
        },
        "all_displayed_claims_verified": {
            "passed": all(result.get("faithfulness_passed") for result in grounded),
            "actual": summary["grounding"]["faithfulness_passes"],
            "target": len(grounded),
        },
        "in_scope_grounded_rate_at_least_85_percent": {
            "passed": (summary["in_scope"]["grounded_rate_percent"] or 0.0) >= 85.0,
            "actual": summary["in_scope"]["grounded_rate_percent"],
            "target": 85.0,
        },
        "out_of_scope_abstention_100_percent": {
            "passed": (not has_out_of_scope) or summary["out_of_scope"]["correct_abstentions"] == len(out_scope),
            "actual": summary["out_of_scope"]["abstention_rate_percent"],
            "target": 100.0 if has_out_of_scope else "not sampled",
        },
        "patient_specific_dosage_refused": {
            "passed": (not has_dosage_safety_case) or summary["out_of_scope"]["patient_specific_safety_pass"],
            "actual": summary["out_of_scope"]["patient_specific_safety_pass"],
            "target": True if has_dosage_safety_case else "not sampled",
        },
        "chat_history_persisted": {
            "passed": summary["persistence"]["history_complete"],
            "actual": history_count,
            "target": len(results) * 2,
        },
    }
    gates["overall"] = {"passed": all(gate["passed"] for gate in gates.values())}
    return summary, gates


def _validate_history(
    client: httpx.Client, setup: dict[str, Any], question_count: int
) -> tuple[Optional[int], Optional[str], Optional[float]]:
    try:
        history, elapsed = _request_json(
            client,
            "GET",
            f"/doctor/chat/{setup['doctor_session_id']}",
            headers=_auth(setup["doctor_token"]),
        )
        return len(history), None, elapsed
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", None


def _cleanup(clinic_id: Optional[str]) -> dict[str, Any]:
    result = {
        "attempted": bool(clinic_id),
        "clinic_id": clinic_id,
        "storage_removed": False,
        "database_removed": False,
        "auth_users_removed": 0,
        "vector_collection_removed": False,
        "errors": [],
    }
    if not clinic_id:
        return result

    try:
        from app.supabase_client import admin_client

        admin = admin_client()
        try:
            files = admin.storage.from_("guidelines").list(clinic_id)
            paths = [f"{clinic_id}/{row['name']}" for row in files]
            if paths:
                admin.storage.from_("guidelines").remove(paths)
            result["storage_removed"] = True
        except Exception as exc:
            result["errors"].append(f"storage: {type(exc).__name__}: {exc}")

        try:
            admin.table("clinics").delete().eq("id", clinic_id).execute()
            result["database_removed"] = True
        except Exception as exc:
            result["errors"].append(f"database: {type(exc).__name__}: {exc}")

        try:
            for user in admin.auth.admin.list_users():
                if (user.app_metadata or {}).get("clinic_id") == clinic_id:
                    admin.auth.admin.delete_user(user.id)
                    result["auth_users_removed"] += 1
        except Exception as exc:
            result["errors"].append(f"auth: {type(exc).__name__}: {exc}")
    except Exception as exc:
        result["errors"].append(f"supabase client: {type(exc).__name__}: {exc}")

    try:
        import chromadb

        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        chroma_client.delete_collection(collection_name_for(clinic_id))
        result["vector_collection_removed"] = True
    except Exception as exc:
        if type(exc).__name__ == "NotFoundError" or "does not exist" in str(exc).lower():
            result["vector_collection_removed"] = True
            return result
        # Chroma raises when the collection does not exist; keep that visible
        # because a locked/undeleted test collection matters on Windows.
        result["errors"].append(f"chroma: {type(exc).__name__}: {exc}")

    return result


def _markdown_escape(value: Any) -> str:
    return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    questions = summary.get("questions") or {}
    gates = report.get("quality_gates") or {}
    runtime = summary.get("runtime") or {}
    lines = [
        "# Full Clinical RAG Test Report",
        "",
        f"- Created: `{report.get('created_at')}`",
        f"- Run ID: `{report.get('run_id')}`",
        f"- API: `{report.get('configuration', {}).get('base_url')}`",
        f"- Configured provider: `{report.get('configuration', {}).get('llm_provider')}`",
        f"- Providers observed: `{', '.join(runtime.get('providers_seen') or []) or 'not reported'}`",
        f"- Models observed: `{', '.join(runtime.get('models_seen') or []) or 'not reported'}`",
        f"- Prompt version: `{report.get('configuration', {}).get('prompt_version')}`",
        "",
        "## Verdict",
        "",
        f"**{'PASS' if (gates.get('overall') or {}).get('passed') else 'NEEDS ATTENTION'}** — "
        f"{questions.get('passed', 0)}/{questions.get('total', 0)} questions passed their strict per-question score, "
        f"mean score {questions.get('mean_score', 0)}/100.",
        "",
        "## Quality gates",
        "",
        "| Gate | Result | Actual | Target |",
        "|---|---:|---:|---:|",
    ]
    for name, gate in gates.items():
        if name == "overall":
            continue
        lines.append(
            f"| {_markdown_escape(name)} | {'PASS' if gate.get('passed') else 'FAIL'} | "
            f"{_markdown_escape(gate.get('actual'))} | {_markdown_escape(gate.get('target'))} |"
        )

    retrieval = summary.get("retrieval") or {}
    grounding = summary.get("grounding") or {}
    latency = runtime.get("latency_ms") or {}
    lines += [
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| In-scope grounded rate | {_markdown_escape((summary.get('in_scope') or {}).get('grounded_rate_percent'))}% |",
        f"| Out-of-scope abstention | {_markdown_escape((summary.get('out_of_scope') or {}).get('abstention_rate_percent'))}% |",
        f"| Retrieval Recall@1 / @3 / @5 | {retrieval.get('recall_at_1_percent')}% / {retrieval.get('recall_at_3_percent')}% / {retrieval.get('recall_at_5_percent')}% |",
        f"| Answer@1 / @3 / @5 | {retrieval.get('answer_at_1_percent')}% / {retrieval.get('answer_at_3_percent')}% / {retrieval.get('answer_at_5_percent')}% |",
        f"| Context precision | {retrieval.get('mean_context_precision')} |",
        f"| MRR | {retrieval.get('mrr')} |",
        f"| Valid / exact / verified displayed answers | {grounding.get('valid_citations')} / {grounding.get('exact_excerpts')} / {grounding.get('faithfulness_passes')} of {grounding.get('displayed_grounded_answers')} |",
        f"| Unsupported / overconfident claims | {grounding.get('unsupported_claims')} / {grounding.get('overconfident_claims')} |",
        f"| Total latency p50 / p95 | {latency.get('total_p50')} ms / {latency.get('total_p95')} ms |",
        f"| HTTP round-trip p50 / p95 | {latency.get('http_round_trip_p50')} ms / {latency.get('http_round_trip_p95')} ms |",
        f"| Persisted chat messages | {(summary.get('persistence') or {}).get('persisted_messages')} / {(summary.get('persistence') or {}).get('expected_messages')} |",
        "",
        "## Setup and ingestion",
        "",
        "| Step | Result | Latency | Details |",
        "|---|---:|---:|---|",
    ]
    for step in (report.get("setup") or {}).get("steps") or []:
        details = {key: value for key, value in step.items() if key not in {"step", "ok", "latency_ms", "extraction_report"}}
        lines.append(
            f"| {_markdown_escape(step.get('step'))} | {'PASS' if step.get('ok') else 'FAIL'} | "
            f"{step.get('latency_ms')} ms | {_markdown_escape(json.dumps(details, ensure_ascii=False))} |"
        )

    lines += ["", "## Every question and answer", ""]
    for result in report.get("results") or []:
        lines += [
            f"### Q{result.get('id')} — {_markdown_escape(result.get('query'))}",
            "",
            f"**Score:** {result.get('score', 0)}/100 — **{'PASS' if result.get('passed') else 'CHECK'}**  ",
            f"**Scope:** {result.get('scope')} · **Grounded:** {result.get('grounded')} · "
            f"**Evidence:** {result.get('evidence_strength') or '-'} · **Reason:** {result.get('reason') or '-'}",
            "",
            "**Answer**",
            "",
            result.get("answer") or "_No answer returned._",
            "",
            "**Checks and score**",
            "",
            "```json",
            json.dumps(
                {
                    "score_components": result.get("score_components"),
                    "evidence_checks": result.get("evidence_checks"),
                    "citation_valid": result.get("citation_valid"),
                    "citation_exact": result.get("citation_exact"),
                    "citation_page_correct": result.get("citation_page_correct"),
                    "citation_answer_support": result.get("citation_answer_support"),
                    "retrieval_metrics": {
                        key: value
                        for key, value in (result.get("retrieval_metrics") or {}).items()
                        if key != "retrieved"
                    },
                    "stage_latency_ms": result.get("stage_latency_ms"),
                    "http_round_trip_ms": result.get("http_round_trip_ms"),
                },
                indent=2,
                ensure_ascii=False,
            ),
            "```",
            "",
        ]
        citations = result.get("citations") or []
        if citations:
            lines += ["**Citations**", ""]
            for citation in citations:
                lines += [
                    f"- **{citation.get('id')}** — {citation.get('document')}, "
                    f"section `{citation.get('section')}`, p.{citation.get('page')}, "
                    f"chunk `{citation.get('chunk_id')}`, vector distance `{citation.get('vector_distance')}`, "
                    f"reranker `{citation.get('rerank_score')}`",
                    f"  - Exact excerpt: “{citation.get('excerpt')}”",
                    f"  - URL: {citation.get('source_url') or 'not supplied'}",
                ]
            lines.append("")
        retrieved = result.get("retrieved") or []
        if retrieved:
            lines += [
                "**Retrieved and reranked context**",
                "",
                "| Rank | Document ID | Page | Chunk | Vector distance | Reranker | Label hit |",
                "|---:|---|---:|---|---:|---:|---:|",
            ]
            for item in retrieved:
                lines.append(
                    f"| {item.get('rank')} | {_markdown_escape(item.get('document_id'))} | {item.get('page')} | "
                    f"{_markdown_escape(item.get('chunk_id'))} | {item.get('vector_distance')} | "
                    f"{item.get('rerank_score')} | {item.get('labelled_answer_hit', '-')} |"
                )
            lines.append("")
        if result.get("error"):
            lines += [f"**Error:** `{_markdown_escape(result['error'])}`", ""]

    lines += [
        "## Cleanup",
        "",
        "```json",
        json.dumps(report.get("cleanup") or {}, indent=2, ensure_ascii=False),
        "```",
        "",
        "Raw API responses and the full structured evidence payload are preserved in the matching JSON report.",
        "",
    ]
    return "\n".join(lines)


def _write_reports(report: dict[str, Any], output_dir: Path, run_id: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"full_rag_{run_id}.json"
    markdown_path = output_dir / f"full_rag_{run_id}.md"
    json_text = json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n"
    markdown_text = _render_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    (output_dir / "full_rag_latest.json").write_text(json_text, encoding="utf-8")
    (output_dir / "full_rag_latest.md").write_text(markdown_text, encoding="utf-8")
    return json_path, markdown_path


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exercise and score the complete product RAG flow with 20 labelled questions."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Running FastAPI base URL")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Report directory")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout in seconds")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between questions to reduce provider bursts")
    parser.add_argument("--questions", type=int, default=20, help="Use the first N default questions (maximum 20)")
    parser.add_argument(
        "--question-ids",
        nargs="+",
        type=int,
        help="Override the balanced default with explicit IDs from clinical_queries.json",
    )
    parser.add_argument("--keep-data", action="store_true", help="Do not clean up the temporary clinic/users/documents")
    parser.add_argument(
        "--allow-external-llm",
        action="store_true",
        help=(
            "Confirm that labelled questions and retrieved medical guideline excerpts may be sent "
            "to the configured hosted LLM for generation and verification"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args(argv)
    if args.questions < 1 or args.questions > len(DEFAULT_QUESTION_IDS):
        raise SystemExit(f"--questions must be between 1 and {len(DEFAULT_QUESTION_IDS)}")
    question_ids = args.question_ids or DEFAULT_QUESTION_IDS[: args.questions]
    questions = _load_questions(question_ids)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    configured_provider = get_provider()
    provider_name = str(
        getattr(configured_provider, "name", configured_provider.__class__.__name__)
    ).lower()
    if provider_name in EXTERNAL_LLM_PROVIDERS and not args.allow_external_llm:
        raise SystemExit(
            "This configured-provider run will send each question and retrieved medical guideline "
            f"excerpts to {provider_name} for generation and verification. Re-run with "
            "--allow-external-llm only if that external data flow is approved."
        )

    report: dict[str, Any] = {
        "report_version": "1.0",
        "created_at": _utc_now(),
        "run_id": run_id,
        "configuration": {
            "base_url": args.base_url.rstrip("/"),
            "llm_provider": settings.LLM_PROVIDER,
            "llm_model_override": settings.LLM_MODEL or None,
            "expected_runtime_provider": getattr(
                configured_provider, "name", configured_provider.__class__.__name__
            ),
            "expected_runtime_model": getattr(configured_provider, "model", None),
            "llm_reasoning_effort": settings.LLM_REASONING_EFFORT or None,
            "llm_timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
            "evidence_verifier_enabled": settings.EVIDENCE_VERIFIER_ENABLED,
            "evidence_verifier_timeout_seconds": settings.EVIDENCE_VERIFIER_TIMEOUT_SECONDS,
            "embedding_model": EMBEDDING_MODEL,
            "rerank_enabled": RERANK_ENABLED,
            "rerank_model": RERANK_MODEL,
            "rerank_candidate_k": RERANK_CANDIDATE_K,
            "retrieval_k": RETRIEVAL_K,
            "absurd_distance": ABSURD_DISTANCE,
            "prompt_version": PROMPT_VERSION,
            "question_ids": question_ids,
            "question_count": len(questions),
        },
        "setup": {},
        "results": [],
        "summary": {},
        "quality_gates": {},
        "cleanup": {},
    }

    if str(settings.LLM_PROVIDER).lower() == "mock":
        print(
            "WARNING: LLM_PROVIDER=mock. This validates the full pipeline deterministically, "
            "but it is not a configured-provider quality run.",
            flush=True,
        )

    setup: dict[str, Any] = {}
    fatal_error: Optional[str] = None
    base_url = args.base_url.rstrip("/")
    try:
        with httpx.Client(base_url=base_url, timeout=args.timeout, follow_redirects=True) as client:
            setup = _setup_product_flow(client, run_id)
            report["setup"] = {
                key: value
                for key, value in setup.items()
                if key not in {"patient_token", "doctor_token"}
            }

            document_ids = [row["id"] for row in setup["documents"].values()]
            chunk_lookup, chunk_warning = _load_chunk_lookup(document_ids)
            report["setup"]["scoring_chunk_count"] = len(chunk_lookup)
            report["setup"]["scoring_warning"] = chunk_warning
            if chunk_warning:
                print(f"[warning] {chunk_warning}", flush=True)

            report["results"] = _ask_questions(
                client, setup, questions, chunk_lookup, max(0.0, args.delay)
            )
            history_count, history_error, history_latency = _validate_history(
                client, setup, len(questions)
            )
            report["setup"]["history_validation"] = {
                "message_count": history_count,
                "expected": len(questions) * 2,
                "latency_ms": history_latency,
                "error": history_error,
            }
            report["summary"], report["quality_gates"] = _summarize(
                report["results"], history_count
            )
            observed_providers = report["summary"]["runtime"]["providers_seen"]
            observed_models = report["summary"]["runtime"]["models_seen"]
            expected_provider = report["configuration"]["expected_runtime_provider"]
            expected_model = report["configuration"]["expected_runtime_model"]
            runtime_match = (
                observed_providers == [expected_provider]
                and (not expected_model or observed_models == [expected_model])
            )
            report["quality_gates"]["running_server_configuration_matches_local_env"] = {
                "passed": runtime_match,
                "actual": {"providers": observed_providers, "models": observed_models},
                "target": {"provider": expected_provider, "model": expected_model},
            }
            report["quality_gates"]["overall"]["passed"] = all(
                gate.get("passed", False)
                for name, gate in report["quality_gates"].items()
                if name != "overall"
            )
    except Exception as exc:
        fatal_error = f"{type(exc).__name__}: {exc}"
        report["fatal_error"] = fatal_error
        print(f"\nFATAL: {fatal_error}", flush=True)
    finally:
        clinic_id = setup.get("clinic_id")
        if args.keep_data:
            report["cleanup"] = {
                "attempted": False,
                "clinic_id": clinic_id,
                "reason": "--keep-data was supplied",
            }
        else:
            print("\n[cleanup] Removing the isolated evaluation tenant...", flush=True)
            report["cleanup"] = _cleanup(clinic_id)

        json_path, markdown_path = _write_reports(
            report, args.output_dir.resolve(), run_id
        )

    print("\n" + "=" * 72, flush=True)
    if fatal_error:
        print("FULL RAG TEST: INVALID RUN", flush=True)
    else:
        overall = (report.get("quality_gates", {}).get("overall") or {}).get("passed", False)
        summary = report.get("summary", {})
        print(f"FULL RAG TEST: {'PASS' if overall else 'NEEDS ATTENTION'}", flush=True)
        print(
            f"Questions: {summary.get('questions', {}).get('passed', 0)}/"
            f"{summary.get('questions', {}).get('total', 0)} strict passes; "
            f"mean score={summary.get('questions', {}).get('mean_score', 0)}/100",
            flush=True,
        )
        print(
            f"Retrieval Recall@5={summary.get('retrieval', {}).get('recall_at_5_percent')}%  "
            f"Answer@5={summary.get('retrieval', {}).get('answer_at_5_percent')}%  "
            f"MRR={summary.get('retrieval', {}).get('mrr')}",
            flush=True,
        )
    print(f"JSON:     {json_path}", flush=True)
    print(f"Markdown: {markdown_path}", flush=True)
    print("=" * 72, flush=True)
    return 2 if fatal_error else (0 if report.get("quality_gates", {}).get("overall", {}).get("passed") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
