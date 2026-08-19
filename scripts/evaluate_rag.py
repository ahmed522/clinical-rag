"""Evaluate retrieval, structured generation, claim evidence, verification, and refusal."""

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import List, Optional, Tuple

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from app.config import settings
from app.llm import MockProvider, get_provider
from app.llm_prompts import PROMPT_VERSION, system_prompt
from app.services.generation import validate_claims, verification_failure
from app.services.safety import personal_clinical_request
from rag.config import (
    ABSURD_DISTANCE,
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QUERIES_PATH,
    RAG_REPORT_PATH,
    RERANK_CANDIDATE_K,
    RERANK_ENABLED,
    RERANK_MODEL,
    RETRIEVAL_K,
)
from rag.rerank import rerank_hits


def load_queries(path: Path = QUERIES_PATH) -> List[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)["queries"]


def load_vectorstore(persist_dir: Path = CHROMA_DIR) -> Chroma:
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL),
        persist_directory=str(persist_dir),
    )


def _source_from_hit(document, distance: float, rerank_score: Optional[float], rank: int) -> dict:
    metadata = document.metadata
    return {
        "rank": rank,
        "text": document.page_content,
        "title": metadata.get("title") or metadata.get("source", "Unknown document"),
        "source": metadata.get("source"),
        "document_id": metadata.get("document_id"),
        "publisher": metadata.get("publisher"),
        "source_url": metadata.get("url"),
        "page_number": metadata.get("page_number"),
        "section_title": metadata.get("section_title"),
        "chunk_id": metadata.get("chunk_id"),
        "distance": round(float(distance), 4),
        "rerank_score": round(float(rerank_score), 4) if rerank_score is not None else None,
    }


def retrieve_for_evaluation(vectorstore: Chroma, question: str) -> Tuple[List[dict], dict]:
    candidate_k = max(RETRIEVAL_K, RERANK_CANDIDATE_K) if RERANK_ENABLED else RETRIEVAL_K
    started = perf_counter()
    hits = vectorstore.similarity_search_with_score(question, k=candidate_k)
    vector_ms = (perf_counter() - started) * 1000
    if not hits or float(hits[0][1]) > ABSURD_DISTANCE:
        return [], {"vector_ms": vector_ms, "rerank_ms": 0.0}

    started = perf_counter()
    ranked = (
        rerank_hits(question, hits, k=RETRIEVAL_K)
        if RERANK_ENABLED
        else [(document, float(distance), None) for document, distance in hits[:RETRIEVAL_K]]
    )
    rerank_ms = (perf_counter() - started) * 1000
    return [
        _source_from_hit(document, distance, score, rank)
        for rank, (document, distance, score) in enumerate(ranked, start=1)
    ], {"vector_ms": vector_ms, "rerank_ms": rerank_ms}


def _citation_numbers(citations: List) -> List[int]:
    values = []
    for citation in citations:
        if isinstance(citation, int) and not isinstance(citation, bool):
            values.append(citation)
        elif isinstance(citation, dict) and isinstance(citation.get("source_id"), int):
            values.append(citation["source_id"])
    return values


def citation_metrics(query: dict, sources: List[dict], citations: List) -> dict:
    numbers = _citation_numbers(citations)
    valid = bool(numbers) and len(numbers) == len(citations) and all(1 <= number <= len(sources) for number in numbers)
    if not valid:
        return {"valid": False, "page_correct": False, "answer_support": False}

    cited_sources = [sources[number - 1] for number in numbers]
    expected_pages = set(query.get("expected_pages") or [])
    expected_source = query.get("expected_source")
    patterns = query.get("must_contain") or []
    page_correct = any(
        source.get("source") == expected_source and source.get("page_number") in expected_pages
        for source in cited_sources
    )
    answer_support = any(
        source.get("source") == expected_source
        and source.get("page_number") in expected_pages
        and (not patterns or any(re.search(pattern, source.get("text", ""), re.IGNORECASE) for pattern in patterns))
        for source in cited_sources
    )
    return {"valid": True, "page_correct": page_correct, "answer_support": answer_support}


def retrieval_metrics(query: dict, sources: List[dict]) -> dict:
    expected_pages = set(query.get("expected_pages") or [])
    expected_source = query.get("expected_source")
    patterns = query.get("must_contain") or []
    relevant = []
    answer_positions = []
    for index, source in enumerate(sources, start=1):
        page_hit = source.get("source") == expected_source and source.get("page_number") in expected_pages
        answer_hit = page_hit and (
            not patterns or any(re.search(pattern, source.get("text", ""), re.IGNORECASE) for pattern in patterns)
        )
        relevant.append(answer_hit)
        if answer_hit:
            answer_positions.append(index)
    return {
        "recall_at_1": any(relevant[:1]),
        "recall_at_3": any(relevant[:3]),
        "recall_at_5": any(relevant[:5]),
        "context_precision": round(sum(relevant) / len(sources), 4) if sources else 0.0,
        "reciprocal_rank": round(1 / answer_positions[0], 4) if answer_positions else 0.0,
    }


def _exact_citations(citations: List[dict], sources: List[dict]) -> bool:
    if not citations:
        return False
    for citation in citations:
        number = citation.get("source_id")
        excerpt = " ".join(str(citation.get("excerpt") or "").split())
        if not isinstance(number, int) or not 1 <= number <= len(sources) or not excerpt:
            return False
        if excerpt not in " ".join(sources[number - 1].get("text", "").split()):
            return False
    return True


def evaluate_query(vectorstore: Chroma, provider, query: dict) -> dict:
    total_started = perf_counter()
    safety_reason = personal_clinical_request(query["query"])
    sources, latency = ([], {"vector_ms": 0.0, "rerank_ms": 0.0})
    result = None
    package = None
    citations: List[dict] = []
    verifier_claims: List[dict] = []
    verification_rows: List[dict] = []
    validation_errors: List[str] = []
    generation_ms = verification_ms = 0.0
    error = None

    if not safety_reason:
        sources, latency = retrieve_for_evaluation(vectorstore, query["query"])
    if sources:
        started = perf_counter()
        try:
            result = provider.complete(system_prompt("general"), sources, query["query"], "")
        except Exception as exc:
            error = f"generation:{type(exc).__name__}:{exc}"[:1000]
        generation_ms = (perf_counter() - started) * 1000

    if result and result.sufficient:
        package, citations, verifier_claims, validation_errors = validate_claims(result, sources)
        if package and not validation_errors:
            started = perf_counter()
            try:
                verification = provider.verify(query["query"], verifier_claims)
                failed, verification_rows = verification_failure(
                    verification, {claim["claim_id"] for claim in verifier_claims}
                )
                if failed:
                    validation_errors.append("semantic_verification_failed")
            except Exception as exc:
                error = f"verification:{type(exc).__name__}:{exc}"[:1000]
            verification_ms = (perf_counter() - started) * 1000

    citation = citation_metrics(query, sources, citations)
    exact = _exact_citations(citations, sources)
    claim_count = len(verifier_claims)
    supported_claims = sum(
        1
        for row in verification_rows
        if row["supported"] and row["relevant"] and row["safe"] and not row["overconfident"]
    )
    coverage = 1.0 if package and claim_count and all(claim.get("excerpts") for claim in verifier_claims) else 0.0
    grounded = bool(
        sources
        and result
        and result.sufficient
        and package
        and not validation_errors
        and not error
        and citation["valid"]
        and exact
        and supported_claims == claim_count
    )
    abstained = not grounded
    retrieval = retrieval_metrics(query, sources)

    return {
        "id": query["id"],
        "query": query["query"],
        "category": query["category"],
        "scope": query["scope"],
        "grounded": grounded,
        "abstained": abstained,
        "answer": package["recommendation"] if package and grounded else "",
        "citations": citations,
        "citation_valid": citation["valid"],
        "citation_exact": exact,
        "citation_page_correct": citation["page_correct"],
        "citation_answer_support": citation["answer_support"],
        "citation_coverage": coverage,
        "claim_count": claim_count,
        "supported_claims": supported_claims,
        "faithfulness": round(supported_claims / claim_count, 4) if claim_count else 0.0,
        "answer_relevant": bool(verification_rows) and all(row["relevant"] for row in verification_rows),
        "safety_passed": bool(verification_rows) and all(row["safe"] for row in verification_rows),
        "overconfident_claims": sum(1 for row in verification_rows if row["overconfident"]),
        "unsupported_claims": max(0, claim_count - supported_claims),
        "safety_refusal": bool(safety_reason and abstained),
        "retrieval_metrics": retrieval,
        "retrieved": [
            {
                "chunk_id": source.get("chunk_id"),
                "source": source.get("source"),
                "page": source.get("page_number"),
                "distance": source.get("distance"),
                "rerank_score": source.get("rerank_score"),
            }
            for source in sources
        ],
        "validation_errors": validation_errors,
        "verification": verification_rows,
        "latency_ms": {
            "vector": round(latency["vector_ms"], 2),
            "rerank": round(latency["rerank_ms"], 2),
            "generation": round(generation_ms, 2),
            "verification": round(verification_ms, 2),
            "total": round((perf_counter() - total_started) * 1000, 2),
        },
        "error": error,
    }


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(float(ordered[index]), 2)


def summarize(results: List[dict]) -> dict:
    in_scope = [row for row in results if row["scope"] == "in_scope"]
    out_of_scope = [row for row in results if row["scope"] == "out_of_scope"]
    totals = [row["latency_ms"]["total"] for row in results]

    def count(rows, field):
        return sum(1 for row in rows if row.get(field))

    claims = sum(row.get("claim_count", 0) for row in results)
    supported = sum(row.get("supported_claims", 0) for row in results)
    grounded_rows = [row for row in results if row.get("grounded")]
    retrieval_rows = [row.get("retrieval_metrics", {}) for row in in_scope]
    return {
        "in_scope": {
            "total": len(in_scope),
            "grounded_answers": count(in_scope, "grounded"),
            "valid_citations": count(in_scope, "citation_valid"),
            "exact_citations": count(in_scope, "citation_exact"),
            "correct_page_citations": count(in_scope, "citation_page_correct"),
            "citation_answer_support": count(in_scope, "citation_answer_support"),
        },
        "out_of_scope": {"total": len(out_of_scope), "correct_abstentions": count(out_of_scope, "abstained")},
        "retrieval": {
            "recall_at_1": count(retrieval_rows, "recall_at_1"),
            "recall_at_3": count(retrieval_rows, "recall_at_3"),
            "recall_at_5": count(retrieval_rows, "recall_at_5"),
            "mean_context_precision": round(
                sum(row.get("context_precision", 0.0) for row in retrieval_rows) / len(retrieval_rows), 4
            ) if retrieval_rows else 0.0,
            "mrr": round(sum(row.get("reciprocal_rank", 0.0) for row in retrieval_rows) / len(retrieval_rows), 4)
            if retrieval_rows else 0.0,
        },
        "claims": {
            "total": claims,
            "supported": supported,
            "faithfulness": round(supported / claims, 4) if claims else 0.0,
            "grounded_with_full_citation_coverage": sum(
                1 for row in grounded_rows if row.get("citation_coverage") == 1.0
            ),
            "unsupported": sum(row.get("unsupported_claims", 0) for row in results),
            "overconfident": sum(row.get("overconfident_claims", 0) for row in results),
        },
        "errors": sum(1 for row in results if row.get("error")),
        "latency_ms": {"p50_total": _percentile(totals, 0.50), "p95_total": _percentile(totals, 0.95)},
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate the complete clinical RAG pipeline")
    parser.add_argument("--provider", choices=("mock", "configured"), default="mock")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=RAG_REPORT_PATH)
    args = parser.parse_args()

    queries = load_queries()
    if args.limit is not None:
        queries = queries[: max(0, args.limit)]
    provider = MockProvider() if args.provider == "mock" else get_provider()
    vectorstore = load_vectorstore()
    results = []
    for index, query in enumerate(queries, start=1):
        print(f"[{index}/{len(queries)}] {query['query'][:70]}")
        results.append(evaluate_query(vectorstore, provider, query))

    report = {
        "report_version": "2.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": getattr(provider, "name", settings.LLM_PROVIDER),
        "llm_model": getattr(provider, "model", None) or settings.LLM_MODEL or None,
        "embedding_model": EMBEDDING_MODEL,
        "rerank_enabled": RERANK_ENABLED,
        "rerank_model": RERANK_MODEL if RERANK_ENABLED else None,
        "candidate_k": RERANK_CANDIDATE_K,
        "context_k": RETRIEVAL_K,
        "prompt_version": PROMPT_VERSION,
        "dataset_size": len(queries),
        "metric_definitions": {
            "faithfulness": "Verifier-supported claims divided by generated clinical claims.",
            "citation_coverage": "Claims with mechanically valid exact evidence divided by claims.",
            "context_precision": "Labelled answer-bearing chunks divided by retrieved chunks.",
        },
        "summary": summarize(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report["summary"], indent=2))
    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
