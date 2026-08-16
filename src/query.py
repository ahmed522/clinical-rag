"""
query.py
--------
Goal: run a set of clinical test queries against the ChromaDB index
built by embed_index.py, and display the retrieved chunks so we can
manually check whether retrieval quality is good.

This is the final deliverable step for today's task: "Run 5-10
clinical queries and display chunks".

Run with:
    python src/query.py
"""

import json
import sys

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# Retrieved clinical text contains characters the default Windows
# console codepage cannot encode (>=, <=, +/-, micro). Printing one
# raises UnicodeEncodeError and kills the run mid-query.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QUERY_RESULTS_PATH as RESULTS_PATH,
    TOP_K,
)

PERSIST_DIR = str(CHROMA_DIR)  # Chroma wants a string, not a Path

# A set of 10 narrow, clinically relevant test queries covering
# different parts of the Type 2 Diabetes guidelines (diagnosis,
# first-line treatment, monitoring, complications, lifestyle).
TEST_QUERIES = [
    "What is the first-line pharmacological treatment for type 2 diabetes?",
    "What HbA1c target should be used for adults with type 2 diabetes?",
    "When should insulin be started in type 2 diabetes management?",
    "What are the benefits of SGLT-2 inhibitors in type 2 diabetes?",
    "How should blood pressure be managed in adults with type 2 diabetes?",
    "What lifestyle and dietary advice is recommended for type 2 diabetes?",
    "How often should HbA1c be monitored in type 2 diabetes?",
    "What are the criteria for diagnosing type 2 diabetes?",
    "How should type 2 diabetes complications be screened for?",
    "What is the second-line treatment option if metformin is not tolerated?",
]


def load_vectorstore() -> Chroma:
    """Load the existing Chroma index from disk (created by embed_index.py)."""
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIR,
    )
    return vectorstore


def run_query(vectorstore: Chroma, query: str, k: int = TOP_K) -> list[dict]:
    """
    Run a single similarity search and return the retrieved chunks in a
    simple, serializable format (with their similarity score and
    metadata) so we can print them and also save them to a JSON file.

    Note: Chroma's similarity_search_with_score returns a distance
    score (lower = more similar) for the default embedding function.
    """
    results = vectorstore.similarity_search_with_score(query, k=k)

    formatted = []
    for doc, score in results:
        formatted.append({
            "score": round(float(score), 4),
            "text": doc.page_content,
            "section_title": doc.metadata.get("section_title"),
            "page_number": doc.metadata.get("page_number"),
            "source": doc.metadata.get("source"),
            "publisher": doc.metadata.get("publisher"),
        })
    return formatted


def print_results(query: str, results: list[dict]) -> None:
    print(f"\nQuery: {query}")
    print("-" * 70)
    for i, r in enumerate(results, start=1):
        preview = r["text"][:250].replace("\n", " ")
        print(
            f"  [{i}] score={r['score']} | {r['publisher']} "
            f"| page {r['page_number']} | section: {r['section_title']}"
        )
        print(f"      {preview}...")
    print()


def main():
    print("Loading vector index...")
    vectorstore = load_vectorstore()
    print(f"Index loaded from: {PERSIST_DIR}\n")

    all_results = {}

    for query in TEST_QUERIES:
        results = run_query(vectorstore, query)
        print_results(query, results)
        all_results[query] = results

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"Saved all query results to: {RESULTS_PATH}")


if __name__ == "__main__":
    main()