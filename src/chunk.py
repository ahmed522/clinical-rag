"""
chunk.py
--------
Goal: take each JSON file produced by ingest.py (in data/extracted/)
and split it into section-aware "chunks" instead of naive fixed-size
splitting.

Approach:
1) Concatenate a document's pages into one long text, while remembering
   which page number each character offset came from (so we can
   recover the page_number for every chunk later).
2) Detect "section headings" using regex patterns common in clinical
   guidelines, e.g.:
      "1.1 Blood glucose management"
      "Diagnosis and classification"
3) Split the text into sections based on those headings.
4) Any section that is too long (bigger than CHUNK_SIZE) is further
   split with RecursiveCharacterTextSplitter (with overlap), while
   still keeping the original section heading as metadata.
5) Each chunk looks like this:
   {
     "chunk_id": "...",
     "text": "...",
     "section_title": "...",
     "page_number": 12,
     "source": "nice_ng28.pdf",
     "title": "...",
     "publisher": "...",
     "url": "...",
     "topic": "Type 2 Diabetes"
   }

Run with:
    python src/chunk.py
"""

import json
import re
import sys
from pathlib import Path

from langchain.text_splitter import RecursiveCharacterTextSplitter

# Clinical text contains characters the default Windows console codepage
# cannot encode (>=, <=, +/-, micro), and printing a chunk preview
# containing one raises UnicodeEncodeError mid-run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CHUNKS_DIR,
    CHUNKS_PATH,
    EXTRACTED_DIR,
    MIN_CHUNK_CHARS,
    PREPROCESSED_DIR,
    SKIPPED_PAGE_TYPES,
)

# Simple heading-detection pattern: a relatively short line that starts
# either with a section number (1, 1.2, 1.2.3) or a capital letter, and
# has no trailing period (i.e. not a regular sentence). Tuned to match
# the typical heading style used in NICE/WHO guidelines.
#
# Note the separator is [ \t]+ and NOT \s+: \s+ matches newlines, which
# made a page footer bind to the following line and produced bogus
# headings like "131\nWhy the committee made these recommendations".
HEADING_PATTERN = re.compile(
    r"^(?P<heading>"
    r"(\d+(\.\d+)*[ \t]+[A-Z][^\n]{2,80})"   # e.g. "1.2 Managing blood glucose"
    r"|"
    r"([A-Z][A-Za-z ,\-]{3,70})"             # e.g. all-caps-ish "Diagnosis"
    r")$",
    re.MULTILINE,
)

# A numbered candidate ("1.5.9 Consider relaxing...") is always a real
# boundary — in NICE guidelines it starts a numbered recommendation, and
# a recommendation is exactly the unit we want to retrieve.
NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*[ \t]+")

# Boilerplate patterns that repeat on every page (page numbers, copyright
# notices) and get falsely matched as headings. Anything matching one of
# these is rejected as a heading candidate.
#
# These are all DOCUMENT-AGNOSTIC by design. This file previously also
# matched two running titles by name ("type 2 diabetes in adults:
# management", "hearts-d"), which only worked for the two guidelines
# originally indexed — useless for a clinic uploading its own documents
# from any specialty. Running titles are now removed upstream by
# preprocessing.py, which detects them by FREQUENCY across pages and so
# generalises to any document.
BOILERPLATE_PATTERNS = [
    re.compile(r"^\d+$"),                                  # a lone page number, e.g. "33"
    re.compile(r"^\d+\s*(of)?\s*\d*$"),                     # "131" / "12 of 131"
    re.compile(r"^page\s+\d+", re.IGNORECASE),
    re.compile(r"©"),                                       # copyright lines
    re.compile(r"all rights reserved", re.IGNORECASE),
    re.compile(r"notice of rights", re.IGNORECASE),
]


def is_boilerplate(heading: str) -> bool:
    """Reject heading candidates that are really just repeated page furniture."""
    normalized = heading.strip().replace("\n", " ")
    if any(p.search(normalized) for p in BOILERPLATE_PATTERNS):
        return True
    # Also test each raw line on its own: normalizing "\n" to " " first
    # meant a lone page number glued to a real line ("131 Contents") no
    # longer matched the ^\d+$ pattern it was written to catch.
    return any(
        any(p.search(line.strip()) for p in BOILERPLATE_PATTERNS)
        for line in heading.splitlines()
    )


def is_probable_heading(heading: str, full_text: str, match_end: int) -> bool:
    """
    Decide whether an *unnumbered* candidate is really a heading.

    The unnumbered branch of HEADING_PATTERN matches any short, capitalised,
    punctuation-free line — which also describes a wrapped line in the middle
    of a sentence ("The blood glucose management protocol is"). Cutting a
    section there splits a clinical statement in half, so we require the
    candidate to actually look like a heading:

      * it is followed by a blank line, or
      * it is ALL CAPS, or
      * it is Title Case (most words capitalised).
    """
    if NUMBERED_HEADING.match(heading):
        return True

    if full_text[match_end:match_end + 2] == "\n\n":
        return True

    letters = [c for c in heading if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return True

    words = [w for w in heading.split() if w.isalpha()]
    if len(words) >= 2:
        capitalised = sum(1 for w in words if w[0].isupper())
        if capitalised / len(words) >= 0.6:
            return True

    return False


def build_full_text_with_page_map(pages: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """
    Concatenate all pages into one text, and also return a "map" that
    links each character offset to a page number, so that when we cut
    a chunk we know which page it started on.

    page_map: list of (start_offset, page_number)
    """
    full_text = ""
    page_map = []
    for p in pages:
        page_map.append((len(full_text), p["page_number"]))
        full_text += p["text"] + "\n"
    return full_text, page_map


def offset_to_page(offset: int, page_map: list[tuple[int, int]]) -> int:
    """Find which page number a given character offset falls into."""
    page_number = page_map[0][1]
    for start_offset, pn in page_map:
        if offset >= start_offset:
            page_number = pn
        else:
            break
    return page_number


def split_into_sections(full_text: str) -> list[dict]:
    """
    Split the full text into sections based on detected headings.
    Each item: {"heading": "...", "start": offset, "end": offset, "text": "..."}

    If no heading is detected at all (rare, but possible), the whole
    text is returned as a single "General" section so the script
    doesn't crash.
    """
    matches = list(HEADING_PATTERN.finditer(full_text))
    if not matches:
        return [{"heading": "General", "start": 0, "end": len(full_text), "text": full_text}]

    # Drop boilerplate matches (page numbers, copyright lines, running
    # titles) BEFORE building section ranges. If we skipped them inside
    # the loop instead, the text "under" a boilerplate heading would be
    # silently dropped instead of staying attached to the real section.
    matches = [
        m for m in matches
        if not is_boilerplate(m.group("heading"))
        and is_probable_heading(m.group("heading"), full_text, m.end())
    ]
    if not matches:
        return [{"heading": "General", "start": 0, "end": len(full_text), "text": full_text}]

    sections = []

    # Text that appears before the first heading used to be discarded
    # silently. Keep it as its own section instead.
    boundaries = [(None, 0, matches[0].start())]
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        boundaries.append((m, m.start(), end))

    for m, start, end in boundaries:
        raw = full_text[start:end]
        stripped = raw.strip()
        if len(stripped) < 30:
            continue  # genuinely empty span, not a heading we are throwing away

        # The heading itself stays INSIDE the section text. It used to be
        # cut out (start = m.end()), which meant the opening clause of
        # almost every numbered recommendation existed only in metadata —
        # and metadata is not embedded, so it was unsearchable.
        lead = len(raw) - len(raw.lstrip())
        sections.append({
            "heading": m.group("heading").strip() if m is not None else "Preamble",
            "start": start + lead,
            "end": end,
            "text": stripped,
        })
    return sections


def make_chunk_id(document_id, page_number: int, index: int) -> str:
    """
    Stable identifier for a chunk.

    Must be DETERMINISTIC: it is the join key between the `chunks` table
    (provenance, source of truth) and the vector store (embeddings), so
    re-ingesting a document has to produce the same ids. This used to be
    uuid4(), which changed on every run and would orphan every
    vector_ref and leave duplicate vectors behind.

    index counts chunks across the whole document rather than restarting
    per page, so two chunks from one page can never collide.
    """

    return f"{document_id}:p{page_number}:c{index}"


def locate_offset(haystack: str, needle: str, search_from: int) -> int:
    """
    Find where a split chunk actually starts inside its section.

    We cannot simply accumulate len(chunk), because the splitter emits
    OVERLAPPING chunks and strips separators — so a running total drifts
    further ahead of the true position with every chunk, and the page
    number derived from it drifts with it.

    Returns -1 if the chunk cannot be located (the caller falls back).
    """
    pos = haystack.find(needle, search_from)
    if pos != -1:
        return pos

    # The splitter strips whitespace, so an exact match can fail. Fall
    # back to a distinctive prefix of the chunk.
    probe = needle[:40]
    if len(probe) >= 20:
        pos = haystack.find(probe, search_from)
        if pos != -1:
            return pos

    return -1


def chunk_document(document: dict, document_id=None) -> list[dict]:
    """
    Take a single document dict (same shape produced by ingest.py) and
    return the list of chunks for it.

    document_id namespaces the chunk ids. The application passes the
    `documents` row id; the CLI omits it and the source filename stem is
    used, which keeps ids stable and readable for the local corpus.
    """
    if document_id is None:
        document_id = Path(document["source"]).stem

    pages = [
        page for page in document["pages"]
        if page.get("page_type", "content") not in SKIPPED_PAGE_TYPES
    ]

    skipped = len(document["pages"]) - len(pages)
    if skipped:
        print(f"  Skipped {skipped} non-content pages (copyright / contents)")

    full_text, page_map = build_full_text_with_page_map(pages)
    sections = split_into_sections(full_text)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = []
    index = 0
    for section in sections:
        sub_texts = splitter.split_text(section["text"])
        cursor = 0          # position within section["text"]
        last_known = 0      # fallback if a chunk cannot be located
        for sub_text in sub_texts:
            if len(sub_text.strip()) < MIN_CHUNK_CHARS:
                continue

            relative = locate_offset(section["text"], sub_text, cursor)
            if relative == -1:
                relative = last_known
            else:
                last_known = relative
                cursor = relative + 1

            page_number = offset_to_page(section["start"] + relative, page_map)
            chunks.append({
                "chunk_id": make_chunk_id(document_id, page_number, index),
                "text": sub_text,
                "section_title": section["heading"],
                "page_number": page_number,
                "source": document["source"],
                "title": document["title"],
                "publisher": document["publisher"],
                "url": document["url"],
                "topic": document["topic"],
            })
            index += 1

    return chunks


def main():
    all_chunks = []

    # Prefer preprocessed documents (page furniture removed, non-content
    # pages labelled). Fall back to raw extraction so the pipeline still
    # runs if preprocessing has not been run — but say so loudly, because
    # the resulting chunks will carry copyright footers and page numbers.
    json_files = sorted(PREPROCESSED_DIR.glob("*.json"))
    source_dir = PREPROCESSED_DIR

    if not json_files:
        json_files = sorted(EXTRACTED_DIR.glob("*.json"))
        source_dir = EXTRACTED_DIR
        if json_files:
            print(
                f"[warning] No preprocessed documents in {PREPROCESSED_DIR} — "
                f"falling back to raw extraction. Run preprocessing.py first "
                f"to strip page furniture."
            )

    if not json_files:
        print(f"No JSON files found in {source_dir} — run ingest.py first.")
        return

    print(f"Reading documents from: {source_dir}")

    required_keys = {"source", "title", "publisher", "url", "topic", "pages"}

    for json_file in json_files:
        with open(json_file, "r", encoding="utf-8") as f:
            document = json.load(f)

        # Defensive check: skip files from an older/different schema
        missing = required_keys - set(document.keys())
        if missing:
            print(
                f"[skipped] {json_file.name} — missing fields: {missing}. "
                f"Delete this file and re-run ingest.py so it's regenerated correctly."
            )
            continue

        print(f"### Chunking: {document['source']} ###")
        chunks = chunk_document(document)
        print(f"Number of chunks: {len(chunks)}")

        # Quick sample for review
        for c in chunks[:2]:
            print(f"  [page {c['page_number']}] {c['section_title']}")
            print(f"  {c['text'][:150]}...\n")

        all_chunks.extend(chunks)

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    print(f"\nTotal chunks across all sources: {len(all_chunks)}")
    print(f"Saved to: {CHUNKS_PATH}")


if __name__ == "__main__":
    main()