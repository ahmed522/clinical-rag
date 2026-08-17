"""
preprocessing.py
----------------
Goal: take the per-document JSON written by ingest.py and remove the
repeated page furniture (running titles, copyright footers, page
numbers) that is not clinical content, then label pages that are not
content at all (copyright pages, tables of contents).

Runs BETWEEN ingest.py and chunk.py:

    ingest.py  ->  data/extracted/*.json
    preprocessing.py  ->  data/preprocessed/*.json
    chunk.py

Why this exists
---------------
The NICE guideline repeats this on 130 of its 131 pages:

    Type 2 diabetes in adults: management (NG28)
    (c) NICE 2026. All rights reserved. Subject to Notice of rights (...)
    Page 41 of
    131

That is ~9% of the document's characters, it lands in most chunks, and
it drags every embedding toward the same meaningless centroid.

How furniture is detected
-------------------------
By FREQUENCY, not by hardcoded regex, so this works on any guideline
added later without editing this file:

  1. A line that appears verbatim near the edge of most pages is
     furniture (catches running titles and copyright blocks).
  2. A line near the edge that has the SHAPE of a page number is
     furniture (catches "41", "Page 41 of", "12 of 131" — these differ
     on every page, so frequency alone would not catch them).

Two guardrails, because this deletes text:

  * Only lines near the top/bottom of a page are considered. A bare
    number in the middle of a page can be a table cell — a dose, an
    eGFR threshold — not a page number.
  * Recommendation numbers ("1.1.1", "1.5.9") are PROTECTED and never
    removed. They appear exactly once each, so frequency would not flag
    them, but they have a page-number-ish shape and they are the
    citation key for every NICE recommendation.

Every removed line pattern is reported, so a human can check what was
dropped before it reaches the index.

Run with:
    python src/preprocessing.py
"""

import json
import re
import sys
from collections import Counter


# Clinical text contains characters the default Windows console codepage
# cannot encode (>=, <=, +/-, micro), and printing one raises
# UnicodeEncodeError part-way through a run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from config import (
    EDGE_LINES,
    EXTRACTED_DIR as INPUT_DIR,
    FURNITURE_PAGE_RATIO,
    MAX_FURNITURE_LINE_LENGTH,
    MIN_PAGES_FOR_DETECTION,
    MIN_TOC_LINES,
    PREPROCESSED_DIR as OUTPUT_DIR,
    TOC_LINE_RATIO,
)


# Lines matching these are NEVER removed, whatever else they look like.
# "1.1.1" is a NICE recommendation number: it is the citation key a
# clinician uses to look the recommendation up, and each one appears
# exactly once in the document.
PROTECTED_PATTERNS = [
    re.compile(r"^\d+(\.\d+)+$"),
]

# Shapes that are page numbers rather than content. These differ on
# every page, so they cannot be caught by frequency alone.
PAGE_NUMBER_SHAPES = [
    re.compile(r"^\d{1,4}$"),
    re.compile(r"^page\s+\d+(\s+of(\s+\d+)?)?$", re.IGNORECASE),
    re.compile(r"^\d+\s+of\s+\d+$", re.IGNORECASE),
]


# ============================================================
# Line classification
# ============================================================

def is_protected(line):
    """Lines that must survive preprocessing no matter what."""

    return any(
        pattern.match(line)
        for pattern in PROTECTED_PATTERNS
    )


def looks_like_page_number(line):
    """Detect page-number furniture such as '41' or 'Page 41 of'."""

    if is_protected(line):
        return False

    return any(
        pattern.match(line)
        for pattern in PAGE_NUMBER_SHAPES
    )


def furniture_key(line):
    """
    Reduce a line to a comparison key: lowercase, no digits, no
    punctuation.

    Matching on the exact string is too brittle. The NICE footer occurs
    in two forms because line-break de-hyphenation turns "terms-and"
    into "termsand" on some pages, so the same footer appears as two
    different strings and each falls under the repetition threshold.

    Collapsing digits is safe here ONLY because is_protected() excludes
    recommendation numbers before this is ever consulted; without that,
    "1.1.1" and "1.5.9" would collapse to the same key and be deleted.
    """

    return re.sub(r"[^a-z]", "", line.lower())


def edge_indices(line_count):
    """Indices considered the top/bottom edge of a page."""

    return set(range(min(EDGE_LINES, line_count))) | set(
        range(max(0, line_count - EDGE_LINES), line_count)
    )


# ============================================================
# Furniture detection
# ============================================================

def detect_furniture(pages):
    """
    Find lines that repeat near the edge of most pages.

    Returns the set of exact line strings considered furniture.
    """

    page_count = len(pages)

    if page_count < MIN_PAGES_FOR_DETECTION:
        return set()

    counts = Counter()

    for page in pages:

        lines = [
            line.strip()
            for line in page.get("text", "").split("\n")
        ]

        edges = edge_indices(len(lines))

        # A set per page: a line repeated twice on one page still only
        # counts as appearing on one page.
        seen_on_this_page = {
            furniture_key(lines[i])
            for i in edges
            if lines[i]
            and len(lines[i]) <= MAX_FURNITURE_LINE_LENGTH
            and not is_protected(lines[i])
        }

        seen_on_this_page.discard("")

        counts.update(seen_on_this_page)

    threshold = max(
        MIN_PAGES_FOR_DETECTION,
        int(page_count * FURNITURE_PAGE_RATIO)
    )

    return {
        key
        for key, count in counts.items()
        if count >= threshold
    }


def strip_furniture(text, furniture):
    """
    Remove furniture lines from the edges of a single page.

    Returns (cleaned_text, list_of_removed_lines).
    """

    lines = text.split("\n")
    edges = edge_indices(len(lines))

    kept = []
    removed = []

    for index, line in enumerate(lines):

        stripped = line.strip()

        if index in edges and stripped and not is_protected(stripped):

            if furniture_key(stripped) in furniture or looks_like_page_number(stripped):
                removed.append(stripped)
                continue

        kept.append(line)

    cleaned = "\n".join(kept)

    # Removing lines can leave gaps behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip(), removed


# ============================================================
# Text cleaning
#
# Deliberately minimal. ingest.py already normalises whitespace, fixes
# ligatures and repairs line-break hyphenation, so repeating that work
# here would only risk changing clinical text twice.
#
# Nothing here lowercases, stems, or strips punctuation: HbA1c, SGLT-2,
# >=7.0 mmol/L and 6.5% must survive verbatim.
# ============================================================

def remove_dot_leaders(text):
    """
    Remove table-of-contents dot leaders:

        Introduction ........................... 9

    The {4,} bound means this cannot touch clinical decimals such as
    6.5 or recommendation numbers such as 1.5.9.
    """

    return re.sub(r"\.{4,}", " ", text)


def clean_text(text):
    """Light cleanup applied after furniture removal."""

    if not text:
        return ""

    text = text.replace(" ", " ")
    text = remove_dot_leaders(text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ============================================================
# Page classification
# ============================================================

def is_empty_page(text):
    """Detect pages with no content left after preprocessing."""

    return len(text.strip()) == 0


def is_probably_copyright_page(text):
    """
    Detect pages that are mainly copyright / licensing information.

    Requires several independent signals, so an ordinary page carrying
    a copyright footer is not misclassified and dropped whole.
    """

    lower_text = text.lower()

    copyright_keywords = [
        "creative commons",
        "copyright",
        "some rights reserved",
        "sales, rights and licensing",
        "third-party materials",
        "general disclaimers"
    ]

    matches = sum(
        1 for keyword in copyright_keywords
        if keyword in lower_text
    )

    return matches >= 2


def toc_line_ratio(text):
    """
    Fraction of lines that look like a contents entry: a line ending in
    a page number ("1.34 Choosing a preparation 109"), or a lone number
    (NICE wraps some contents page numbers onto their own line).
    """

    lines = [
        line.strip()
        for line in text.split("\n")
        if line.strip()
    ]

    if len(lines) < MIN_TOC_LINES:
        return 0.0

    entries = sum(
        1 for line in lines
        if re.search(r"\s\d{1,3}$", line)
        or re.fullmatch(r"\d{1,3}", line)
    )

    return entries / len(lines)


def is_probably_toc_page(text):
    """
    Detect table-of-contents pages.

    Two independent signals, because keywords alone missed the NICE
    contents pages (3-5): they say "Contents" once and nothing else from
    the keyword list, yet they are pure navigation.

    The structural test separates cleanly on these documents: real
    contents pages score 0.34-1.00, while the highest-scoring page of
    actual clinical content scores 0.08 — including pages that are
    mostly tables, which is the case this could plausibly damage.
    """

    lower_text = text.lower()

    toc_keywords = [
        "contents",
        "acknowledgements",
        "abbreviations",
        "figures",
        "tables"
    ]

    matches = sum(
        1 for keyword in toc_keywords
        if keyword in lower_text
    )

    if matches >= 2:
        return True

    return toc_line_ratio(text) >= TOC_LINE_RATIO


# ============================================================
# Document processing
# ============================================================

def process_document(document):
    """
    Preprocess a single document produced by ingest.py, preserving all
    of its provenance metadata.
    """

    pages = document.get("pages", [])

    furniture = detect_furniture(pages)

    processed_pages = []
    removed_counter = Counter()
    dropped_pages = []

    for page in pages:

        page_number = page.get("page_number")

        text, removed = strip_furniture(
            page.get("text", ""),
            furniture
        )

        removed_counter.update(removed)

        text = clean_text(text)

        if is_empty_page(text):
            dropped_pages.append((page_number, "empty"))
            continue

        page_type = "content"

        if is_probably_copyright_page(text):
            page_type = "copyright"

        elif is_probably_toc_page(text):
            page_type = "table_of_contents"

        if page_type != "content":
            dropped_pages.append((page_number, page_type))

        processed_pages.append({
            "page_number": page_number,
            "page_type": page_type,
            "text": text,
            "char_count": len(text)
        })

    # Carry every field through, so provenance (title, publisher, url,
    # topic) survives to the chunk metadata unchanged.
    processed = dict(document)
    processed["pages"] = processed_pages
    processed["processed_pages"] = len(processed_pages)

    return processed, removed_counter, dropped_pages


def report(document, removed_counter, dropped_pages, original_chars):
    """Print what was removed, so a human can audit it."""

    new_chars = sum(
        page["char_count"]
        for page in document["pages"]
    )

    saved = original_chars - new_chars

    print(f"\n### {document['source']} ###")
    print(f"Pages kept: {document['processed_pages']} / {document.get('total_pages', 0)}")

    print(
        f"Characters: {original_chars:,} -> {new_chars:,} "
        f"({saved:,} removed, {100 * saved / max(original_chars, 1):.1f}%)"
    )

    if removed_counter:
        print("\nRemoved line patterns (top 10):")
        for line, count in removed_counter.most_common(10):
            preview = line[:80]
            print(f"  {count:>4}x  {preview}")

    if dropped_pages:
        print("\nPages flagged as non-content:")
        for page_number, reason in dropped_pages[:15]:
            print(f"  page {page_number}: {reason}")


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 60)
    print("Clinical RAG - Preprocessing")
    print("=" * 60)

    json_files = sorted(INPUT_DIR.glob("*.json"))

    if not json_files:
        print(f"No JSON files found in {INPUT_DIR} - run ingest.py first.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    required_keys = {"source", "pages"}

    total_in = 0
    total_out = 0

    for json_file in json_files:

        with open(json_file, "r", encoding="utf-8") as f:
            document = json.load(f)

        missing = required_keys - set(document.keys())
        if missing:
            print(
                f"[skipped] {json_file.name} - missing fields: {missing}. "
                f"Re-run ingest.py so it is regenerated correctly."
            )
            continue

        original_chars = sum(
            len(page.get("text", ""))
            for page in document.get("pages", [])
        )

        processed, removed_counter, dropped_pages = process_document(document)

        report(processed, removed_counter, dropped_pages, original_chars)

        output_path = OUTPUT_DIR / json_file.name

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(processed, f, ensure_ascii=False, indent=2)

        print(f"Saved to: {output_path}")

        total_in += original_chars
        total_out += sum(p["char_count"] for p in processed["pages"])

    print("\n" + "=" * 60)
    print(
        f"Corpus: {total_in:,} -> {total_out:,} characters "
        f"({100 * (total_in - total_out) / max(total_in, 1):.1f}% furniture removed)"
    )
    print("Preprocessing completed. Next: python src/chunk.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
