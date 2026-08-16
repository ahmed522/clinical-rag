import json
import re
import statistics
import sys
from collections import Counter, defaultdict


# Clinical text contains characters the default Windows console codepage
# (cp1252) cannot encode — ≥, ≤, ±, µ — and printing one raised
# UnicodeEncodeError, killing the evaluation part-way through.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ============================================================
# Paths
# ============================================================

# The live chunker (chunk.py) writes CHUNKS_PATH. This used to point at
# data/processed/chunks.json, which belonged to the older pipeline — so
# the evaluation was reporting on data that was not in the index.
from config import (
    CHUNKS_PATH as CHUNKS_FILE,
    EXTRACTED_DIR,
    PREPROCESSED_DIR,
)


# ============================================================
# Configuration
# ============================================================

SMALL_CHUNK_THRESHOLD = 100
VERY_SMALL_CHUNK_THRESHOLD = 50
LARGE_CHUNK_THRESHOLD = 1200


# ============================================================
# Load Chunks
# ============================================================

def load_chunks():
    """
    Load chunks from data/chunks/chunks.json.
    """

    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(
            f"\nChunks file not found:\n{CHUNKS_FILE}\n"
        )

    with open(
        CHUNKS_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    # Accepts both shapes the project has used:
    #   a flat list of chunks              (chunk.py, current)
    #   {"total_chunks": N, "chunks": [..]} (chunking.py, older)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        chunks = data.get("chunks")
        if isinstance(chunks, list):
            return chunks

    raise ValueError(
        "Invalid chunks.json format. Expected a list of chunks, "
        "or an object with a 'chunks' list."
    )


# ============================================================
# Character Statistics
# ============================================================

def evaluate_character_statistics(chunks):
    """
    Evaluate character count statistics.
    """

    char_counts = [
        len(chunk.get("text", ""))
        for chunk in chunks
    ]

    if not char_counts:
        print("\nNo chunks found.")
        return

    print("\n--- Character Statistics ---")

    print(f"Min:     {min(char_counts)}")
    print(f"Max:     {max(char_counts)}")
    print(f"Average: {statistics.mean(char_counts):.2f}")
    print(f"Median:  {statistics.median(char_counts):.2f}")


# ============================================================
# Word Statistics
# ============================================================

def evaluate_word_statistics(chunks):
    """
    Evaluate word count statistics.
    """

    word_counts = [
        len(chunk.get("text", "").split())
        for chunk in chunks
    ]

    if not word_counts:
        return

    print("\n--- Word Statistics ---")

    print(f"Min:     {min(word_counts)}")
    print(f"Max:     {max(word_counts)}")
    print(f"Average: {statistics.mean(word_counts):.2f}")
    print(f"Median:  {statistics.median(word_counts):.2f}")


# ============================================================
# Small Chunks
# ============================================================

def evaluate_small_chunks(chunks):
    """
    Find chunks that are unusually small.
    """

    small_chunks = [
        chunk
        for chunk in chunks
        if len(chunk.get("text", "").strip())
        < SMALL_CHUNK_THRESHOLD
    ]

    very_small_chunks = [
        chunk
        for chunk in chunks
        if len(chunk.get("text", "").strip())
        < VERY_SMALL_CHUNK_THRESHOLD
    ]

    print("\n--- Small Chunks ---")

    print(
        f"Chunks < {SMALL_CHUNK_THRESHOLD} characters: "
        f"{len(small_chunks)}"
    )

    print(
        f"Chunks < {VERY_SMALL_CHUNK_THRESHOLD} characters: "
        f"{len(very_small_chunks)}"
    )

    if small_chunks:
        print("\nExamples:")

        for chunk in small_chunks[:10]:

            print("\n" + chunk.get("chunk_id", "Unknown"))

            print(
                f"Source: {chunk.get('source', 'Unknown')}"
            )

            print(
                f"Page: {chunk.get('page_number', 'Unknown')}"
            )

            print(
                f"Text: {chunk.get('text', '')[:300]}"
            )


# ============================================================
# Large Chunks
# ============================================================

def evaluate_large_chunks(chunks):
    """
    Find chunks that reach or exceed the configured size.
    """

    large_chunks = [
        chunk
        for chunk in chunks
        if len(chunk.get("text", "").strip())
        >= LARGE_CHUNK_THRESHOLD
    ]

    print("\n--- Large Chunks ---")

    print(
        f"Chunks >= {LARGE_CHUNK_THRESHOLD} characters: "
        f"{len(large_chunks)}"
    )

    if large_chunks:

        print("\nExamples:")

        for chunk in large_chunks[:5]:

            print("\n" + chunk.get("chunk_id", "Unknown"))

            print(
                f"Characters: "
                f"{len(chunk.get('text', ''))}"
            )

            print(
                f"Text: {chunk.get('text', '')[:300]}"
            )


# ============================================================
# Duplicate Chunks
# ============================================================

def evaluate_duplicates(chunks):
    """
    Detect duplicated chunk texts.
    """

    text_counter = Counter(
        chunk.get("text", "").strip()
        for chunk in chunks
        if chunk.get("text", "").strip()
    )

    duplicates = {
        text: count
        for text, count in text_counter.items()
        if count > 1
    }

    print("\n--- Duplicate Chunks ---")

    print(
        f"Duplicated texts: {len(duplicates)}"
    )

    if not duplicates:
        print("No duplicated chunks found.")
        return

    print("\nExamples:")

    for text, count in list(
        duplicates.items()
    )[:5]:

        print(f"\nRepeated {count} times:")

        print(text[:500])


# ============================================================
# Metadata Validation
# ============================================================

def evaluate_metadata(chunks):
    """
    Check whether every chunk contains
    the required metadata.
    """

    # Matches the schema produced by chunk.py. Provenance fields are
    # required, not optional: a chunk we cannot attribute to a source,
    # page and publisher must never reach the index.
    required_fields = [
        "chunk_id",
        "source",
        "page_number",
        "section_title",
        "text",
        "title",
        "publisher",
        "url",
        "topic"
    ]

    invalid_chunks = []

    for chunk in chunks:

        missing_fields = [
            field
            for field in required_fields
            if field not in chunk
        ]

        if missing_fields:

            invalid_chunks.append(
                {
                    "chunk": chunk,
                    "missing": missing_fields
                }
            )

    print("\n--- Metadata Check ---")

    if not invalid_chunks:

        print(
            "✓ All chunks contain required metadata."
        )

    else:

        print(
            f"✗ {len(invalid_chunks)} chunks "
            f"have missing metadata."
        )

        for item in invalid_chunks[:5]:

            print(
                f"\nChunk: "
                f"{item['chunk'].get('chunk_id', 'Unknown')}"
            )

            print(
                f"Missing: {item['missing']}"
            )


# ============================================================
# Character Count Consistency
# ============================================================

def evaluate_char_count_consistency(chunks):
    """
    Check whether stored char_count matches
    the actual text length.
    """

    inconsistent = []

    for chunk in chunks:

        text = chunk.get("text", "")

        stored_count = chunk.get(
            "char_count"
        )

        # The current schema does not store char_count; only validate
        # chunks that actually carry one.
        if stored_count is None:
            continue

        actual_count = len(text)

        if stored_count != actual_count:

            inconsistent.append(
                (
                    chunk.get(
                        "chunk_id",
                        "Unknown"
                    ),
                    stored_count,
                    actual_count
                )
            )

    print("\n--- Character Count Consistency ---")

    if not inconsistent:

        print(
            "✓ All char_count values are correct."
        )

    else:

        print(
            f"✗ {len(inconsistent)} chunks "
            f"have incorrect char_count."
        )

        for item in inconsistent[:5]:

            print(
                f"\n{item[0]}"
            )

            print(
                f"Stored: {item[1]} | "
                f"Actual: {item[2]}"
            )


# ============================================================
# Page Citation Correctness
#
# The most important check in this file. Every answer this system
# produces will cite a source and a page so a clinician can verify it.
# If a chunk's text is not actually on the page it claims, the citation
# is fabricated — which is worse than returning no citation at all.
# ============================================================

def normalize_for_match(text):
    """Collapse all whitespace so PDF line breaks don't defeat matching."""

    return re.sub(r"\s+", " ", text).strip()


def load_extracted_pages():
    """
    Load the extracted documents as {source: {page_number: text}}.

    Returns an empty dict if extraction output is unavailable, so the
    rest of the evaluation can still run.
    """

    pages_by_source = {}

    # Must mirror chunk.py's input selection. Checking chunks built from
    # preprocessed text against the raw extraction reports false
    # failures, because removing a page footer changes where a page's
    # text begins and ends.
    source_dir = (
        PREPROCESSED_DIR
        if any(PREPROCESSED_DIR.glob("*.json"))
        else EXTRACTED_DIR
    )

    if not source_dir.exists():
        return pages_by_source

    print(f"Verifying against: {source_dir}")

    for json_file in sorted(source_dir.glob("*.json")):

        with open(json_file, "r", encoding="utf-8") as f:
            document = json.load(f)

        if "source" not in document or "pages" not in document:
            continue

        pages_by_source[document["source"]] = {
            page["page_number"]: page.get("text", "")
            for page in document["pages"]
        }

    return pages_by_source


def evaluate_page_citations(chunks):
    """
    Verify that each chunk's text really appears on the page it cites.

    A chunk may legitimately start near the end of one page and run onto
    the next, so a chunk is also accepted if its opening text is found
    across the cited page and the one following it.
    """

    print("\n--- Page Citation Correctness ---")

    pages_by_source = load_extracted_pages()

    if not pages_by_source:
        print(
            "Skipped: no extracted documents found in "
            f"{EXTRACTED_DIR} — run ingest.py first."
        )
        return

    exact = 0
    spanning = 0
    wrong = []
    skipped = 0

    for chunk in chunks:

        source = chunk.get("source")
        cited_page = chunk.get("page_number")

        pages = pages_by_source.get(source)

        if pages is None or cited_page is None:
            skipped += 1
            continue

        probe = normalize_for_match(
            chunk.get("text", "")
        )[:60]

        if len(probe) < 20:
            skipped += 1
            continue

        cited_text = normalize_for_match(
            pages.get(cited_page, "")
        )

        if probe in cited_text:
            exact += 1
            continue

        joined = normalize_for_match(
            pages.get(cited_page, "")
            + " "
            + pages.get(cited_page + 1, "")
        )

        if probe in joined:
            spanning += 1
            continue

        wrong.append(
            (
                chunk.get("chunk_id", "Unknown"),
                source,
                cited_page,
                probe
            )
        )

    checked = exact + spanning + len(wrong)

    print(f"Chunks checked:            {checked}")
    print(f"Text on cited page:        {exact}")
    print(f"Starts at a page boundary: {spanning}")
    print(f"Not skippable/too short:   {skipped}")

    if not wrong:
        print(
            "\n✓ Every chunk's text was found on the page it cites."
        )
        return

    print(
        f"\n✗ {len(wrong)} chunks cite a page "
        f"their text does not appear on."
    )

    for chunk_id, source, page, probe in wrong[:10]:

        print(f"\n{chunk_id}")
        print(f"Claims: {source} page {page}")
        print(f"Text:   {probe}...")


# ============================================================
# Sentence Boundary Quality
# ============================================================

def evaluate_sentence_boundaries(chunks):
    """
    Report how many chunks start or end mid-sentence.

    A chunk cut mid-sentence can lose a negation or a qualifier
    ("do not offer", "only if"), which inverts clinical meaning.
    """

    if not chunks:
        return

    starts_mid = 0
    ends_mid = 0

    for chunk in chunks:

        text = chunk.get("text", "").strip()

        if not text:
            continue

        if text[0].islower():
            starts_mid += 1

        if not text.endswith((".", ":", "?", "!", ";", "]")):
            ends_mid += 1

    total = len(chunks)

    print("\n--- Sentence Boundaries ---")

    print(
        f"Starts mid-sentence: {starts_mid}/{total} "
        f"({100 * starts_mid / total:.1f}%)"
    )

    print(
        f"Ends mid-sentence:   {ends_mid}/{total} "
        f"({100 * ends_mid / total:.1f}%)"
    )


# ============================================================
# Boilerplate Contamination
# ============================================================

def evaluate_boilerplate(chunks):
    """
    Report chunks carrying page furniture (copyright blocks, running
    headers, table-of-contents dot leaders) rather than clinical text.
    """

    patterns = [
        re.compile(r"©"),
        re.compile(r"all rights reserved", re.IGNORECASE),
        re.compile(r"notice of rights", re.IGNORECASE),
        re.compile(r"\.{4,}"),
        re.compile(r"page \d+ of \d+", re.IGNORECASE),
    ]

    contaminated = [
        chunk
        for chunk in chunks
        if any(
            p.search(chunk.get("text", ""))
            for p in patterns
        )
    ]

    total = len(chunks)

    print("\n--- Boilerplate Contamination ---")

    print(
        f"Chunks containing page furniture: "
        f"{len(contaminated)}/{total} "
        f"({100 * len(contaminated) / total:.1f}%)"
    )


# ============================================================
# Page Distribution
# ============================================================

def evaluate_page_distribution(chunks):
    """
    Show how chunks are distributed across pages.
    """

    page_distribution = defaultdict(int)

    for chunk in chunks:

        source = chunk.get(
            "source",
            "unknown"
        )

        page = chunk.get(
            "page_number",
            "unknown"
        )

        page_distribution[
            (source, page)
        ] += 1

    print("\n--- Page Distribution ---")

    pages = set(
        page
        for _, page in page_distribution.keys()
    )

    print(
        f"Pages represented: {len(pages)}"
    )

    print("\nChunks per page examples:")

    for (
        source,
        page
    ), count in list(
        page_distribution.items()
    )[:15]:

        print(
            f"{source} | "
            f"Page {page}: "
            f"{count} chunks"
        )


# ============================================================
# Source Distribution
# ============================================================

def evaluate_source_distribution(chunks):
    """
    Show how chunks are distributed between documents.
    """

    source_counter = Counter(
        chunk.get(
            "source",
            "unknown"
        )
        for chunk in chunks
    )

    print("\n--- Source Distribution ---")

    for source, count in source_counter.items():

        print(
            f"{source}: {count} chunks"
        )


# ============================================================
# Size Consistency
# ============================================================

def evaluate_size_consistency(chunks):
    """
    Evaluate how consistent the chunk sizes are.
    """

    char_counts = [
        len(chunk.get("text", ""))
        for chunk in chunks
        if chunk.get("text", "").strip()
    ]

    if not char_counts:
        return

    very_small = [
        size
        for size in char_counts
        if size < SMALL_CHUNK_THRESHOLD
    ]

    very_large = [
        size
        for size in char_counts
        if size > LARGE_CHUNK_THRESHOLD
    ]

    print("\n--- Size Consistency ---")

    print(
        f"Average chunk size: "
        f"{statistics.mean(char_counts):.2f} characters"
    )

    print(
        f"Very small chunks: "
        f"{len(very_small)}"
    )

    print(
        f"Very large chunks: "
        f"{len(very_large)}"
    )


# ============================================================
# Chunk Examples
# ============================================================

def show_chunk_examples(chunks):
    """
    Display representative chunk examples.
    """

    if not chunks:
        return

    print("\n" + "=" * 60)
    print("CHUNK EXAMPLES")
    print("=" * 60)

    # First chunk
    examples = []

    examples.append(chunks[0])

    # Middle chunk
    examples.append(
        chunks[len(chunks) // 2]
    )

    # Last chunk
    examples.append(chunks[-1])

    # Remove duplicates by chunk_id
    seen = set()
    unique_examples = []

    for chunk in examples:

        chunk_id = chunk.get(
            "chunk_id"
        )

        if chunk_id not in seen:

            seen.add(chunk_id)

            unique_examples.append(
                chunk
            )

    for chunk in unique_examples:

        print("\n" + "-" * 60)

        print(
            f"ID:      "
            f"{chunk.get('chunk_id', 'Unknown')}"
        )

        print(
            f"Source:  "
            f"{chunk.get('source', 'Unknown')}"
        )

        print(
            f"Page:    "
            f"{chunk.get('page_number', 'Unknown')}"
        )

        print(
            f"Index:   "
            f"{chunk.get('chunk_index', 'Unknown')}"
        )

        print("\nText:")

        print(
            chunk.get("text", "")
        )


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 60)
    print("CHUNKING EVALUATION")
    print("=" * 60)

    print(
        f"\nLoading chunks from:\n{CHUNKS_FILE}"
    )

    # --------------------------------------------------------
    # Load chunks
    # --------------------------------------------------------

    chunks = load_chunks()

    print(
        f"\nTotal chunks: {len(chunks)}"
    )

    # --------------------------------------------------------
    # Run evaluations
    # --------------------------------------------------------

    evaluate_character_statistics(
        chunks
    )

    evaluate_word_statistics(
        chunks
    )

    evaluate_small_chunks(
        chunks
    )

    evaluate_large_chunks(
        chunks
    )

    evaluate_duplicates(
        chunks
    )

    evaluate_metadata(
        chunks
    )

    evaluate_char_count_consistency(
        chunks
    )

    evaluate_page_citations(
        chunks
    )

    evaluate_sentence_boundaries(
        chunks
    )

    evaluate_boilerplate(
        chunks
    )

    evaluate_page_distribution(
        chunks
    )

    evaluate_source_distribution(
        chunks
    )

    evaluate_size_consistency(
        chunks
    )

    show_chunk_examples(
        chunks
    )

    # --------------------------------------------------------
    # Done
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("Evaluation completed.")
    print("=" * 60)


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    main()