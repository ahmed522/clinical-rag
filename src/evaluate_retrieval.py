"""
evaluate_retrieval.py
---------------------
Goal: measure how well retrieval actually works, against the labelled
set in evaluation/clinical_queries.json.

This is the regression gate for every future retrieval change. Swapping
the embedding model, adding a reranker, or changing chunk size is
guesswork until this number moves.

Two metrics, because they fail differently:

  recall@k       - did a chunk from the right source and page appear in
                   the top k?
  answer@k       - stricter: did that chunk also contain the expected
                   text? Catches retrieving the right page but the wrong
                   part of it.

Plus out-of-scope rejection: for questions the documents cannot answer,
the best match should be far enough away that the system can abstain.
That number is the safety-critical one — a clinical system that always
answers is more dangerous than one that says "not covered here".

Run with:
    python src/evaluate_retrieval.py
"""

import json
import re
import sys
from collections import defaultdict

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ============================================================
# Paths and configuration
# ============================================================

from config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QUERIES_PATH,
    RERANK_CANDIDATE_K,
    RERANK_ENABLED,
    RETRIEVAL_REPORT_PATH as RESULTS_PATH,
    TOP_K as MAX_K,
)
from rerank import rerank_hits

PERSIST_DIR = str(CHROMA_DIR)  # Chroma wants a string, not a Path

# Cut-offs the report breaks recall down by, capped at what we retrieve.
REPORT_AT = [k for k in (1, 3, 5, 10) if k <= MAX_K]


# ============================================================
# Loading
# ============================================================

def load_queries():

    if not QUERIES_PATH.exists():
        raise FileNotFoundError(f"\nLabelled query set not found:\n{QUERIES_PATH}\n")

    with open(QUERIES_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    return spec["queries"]


def load_vectorstore():

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIR,
    )


# ============================================================
# Relevance judgements
# ============================================================

def is_page_hit(document, query_spec):
    """The chunk comes from the source and page the answer lives on."""

    return (
        document.metadata.get("source") == query_spec["expected_source"]
        and document.metadata.get("page_number") in query_spec["expected_pages"]
    )


def is_answer_hit(document, query_spec):
    """Stricter: the chunk also contains the expected text."""

    if not is_page_hit(document, query_spec):
        return False

    patterns = query_spec.get("must_contain") or []

    if not patterns:
        return True

    return any(
        re.search(pattern, document.page_content, re.IGNORECASE)
        for pattern in patterns
    )


def first_rank(documents, predicate):
    """1-based rank of the first matching document, or None."""

    for index, document in enumerate(documents, start=1):
        if predicate(document):
            return index

    return None


# ============================================================
# In-scope evaluation
# ============================================================

def evaluate_in_scope(vectorstore, queries):

    results = []

    for query_spec in queries:

        candidate_k = max(MAX_K, RERANK_CANDIDATE_K) if RERANK_ENABLED else MAX_K
        hits = vectorstore.similarity_search_with_score(
            query_spec["query"],
            k=candidate_k
        )
        if RERANK_ENABLED:
            ranked = rerank_hits(query_spec["query"], hits, k=MAX_K)
            documents = [document for document, _, _ in ranked]
        else:
            documents = [document for document, _ in hits[:MAX_K]]
        scores = [score for _, score in hits]

        results.append({
            "id": query_spec["id"],
            "query": query_spec["query"],
            "category": query_spec["category"],
            "expected": f"{query_spec['expected_source']} p{query_spec['expected_pages']}",
            "page_rank": first_rank(documents, lambda d: is_page_hit(d, query_spec)),
            "answer_rank": first_rank(documents, lambda d: is_answer_hit(d, query_spec)),
            "best_score": round(float(scores[0]), 4) if scores else None,
        })

    return results


def report_in_scope(results):

    total = len(results)

    print("\n" + "=" * 74)
    print("IN-SCOPE RETRIEVAL")
    print("=" * 74)

    print(f"\n{'k':>4}  {'recall@k':>10}  {'answer@k':>10}")
    print("-" * 30)

    for k in REPORT_AT:

        recall = sum(
            1 for r in results
            if r["page_rank"] and r["page_rank"] <= k
        )

        answer = sum(
            1 for r in results
            if r["answer_rank"] and r["answer_rank"] <= k
        )

        print(f"{k:>4}  {recall:>4}/{total:<5}  {answer:>4}/{total:<5}")

    # Mean reciprocal rank rewards ranking the answer higher, not just
    # getting it somewhere in the list.
    reciprocal = [
        1 / r["page_rank"] if r["page_rank"] else 0.0
        for r in results
    ]

    print(f"\nMRR (page-level): {sum(reciprocal) / total:.3f}")

    # Per-category, to show WHERE retrieval is weak rather than just that
    # it is weak.
    by_category = defaultdict(lambda: [0, 0])

    for r in results:
        by_category[r["category"]][1] += 1
        if r["page_rank"] and r["page_rank"] <= 5:
            by_category[r["category"]][0] += 1

    print("\n--- recall@5 by category ---")
    for category in sorted(by_category):
        hit, n = by_category[category]
        print(f"  {category:<24} {hit}/{n}")

    misses = [r for r in results if not r["page_rank"]]

    print(f"\n--- misses (answer not in top {MAX_K}): {len(misses)} ---")
    for r in misses:
        print(f"  id{r['id']:>3} {r['query'][:60]}")
        print(f"        expected {r['expected']}")

    weak = [
        r for r in results
        if r["page_rank"] and r["page_rank"] > 3
    ]

    print(f"\n--- retrieved but ranked poorly (rank 4-{MAX_K}): {len(weak)} ---")
    for r in weak:
        print(f"  id{r['id']:>3} rank {r['page_rank']:>2}  {r['query'][:58]}")

    mismatched = [
        r for r in results
        if r["page_rank"] and not r["answer_rank"]
    ]

    if mismatched:
        print(f"\n--- right page, wrong content: {len(mismatched)} ---")
        for r in mismatched:
            print(f"  id{r['id']:>3} {r['query'][:60]}")

    return results


# ============================================================
# Out-of-scope evaluation
# ============================================================

def evaluate_out_of_scope(vectorstore, queries):

    print("\n" + "=" * 74)
    print("OUT-OF-SCOPE REJECTION")
    print("=" * 74)
    print("\nThese questions cannot be answered from the indexed documents.")
    print("A safe system abstains rather than returning plausible-looking text.\n")

    rejected = 0
    results = []

    for query_spec in queries:

        hits = vectorstore.similarity_search_with_score(
            query_spec["query"],
            k=1
        )

        best_score = float(hits[0][1]) if hits else None
        threshold = query_spec.get("abstain_above", 0.75)

        would_abstain = best_score is not None and best_score > threshold
        rejected += would_abstain

        status = "ABSTAIN ✓" if would_abstain else "WOULD ANSWER ✗"

        print(f"  {status:<16} score={best_score:.3f} (abstain above {threshold})")
        print(f"      {query_spec['query'][:66]}")

        if not would_abstain:
            print(f"      -> would have returned: "
                  f"{hits[0][0].page_content[:70]}".replace("\n", " "))

        results.append({
            "id": query_spec["id"],
            "query": query_spec["query"],
            "best_score": round(best_score, 4) if best_score else None,
            "abstains": bool(would_abstain),
        })

    print(f"\ncorrectly rejected: {rejected}/{len(queries)}")

    return results


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 74)
    print("RETRIEVAL EVALUATION")
    print("=" * 74)

    queries = load_queries()

    in_scope = [q for q in queries if q["scope"] == "in_scope"]
    out_of_scope = [q for q in queries if q["scope"] == "out_of_scope"]

    print(f"\nLabelled queries: {len(in_scope)} in scope, "
          f"{len(out_of_scope)} out of scope")
    print(f"Embedding model:  {EMBEDDING_MODEL}")
    print(f"Retrieving top {MAX_K} per query...")

    vectorstore = load_vectorstore()

    in_scope_results = report_in_scope(
        evaluate_in_scope(vectorstore, in_scope)
    )

    out_of_scope_results = evaluate_out_of_scope(vectorstore, out_of_scope)

    report = {
        "embedding_model": EMBEDDING_MODEL,
        "max_k": MAX_K,
        "in_scope": in_scope_results,
        "out_of_scope": out_of_scope_results,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 74)
    print(f"Report saved to: {RESULTS_PATH}")
    print("=" * 74)


if __name__ == "__main__":
    main()
