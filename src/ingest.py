import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

# Extracted clinical text contains characters the default Windows
# console codepage cannot encode (>=, <=, +/-, micro). Printing a page
# preview containing one raises UnicodeEncodeError mid-run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from config import SOURCE_DIR, EXTRACTED_DIR as OUTPUT_DIR


# =========================
# Source metadata
# Each PDF file must be linked to metadata about its source, so we can
# use it later in the chunk metadata and in the source-credibility docs.
# The dict key must match the PDF filename exactly as it appears in
# data/source/
# =========================

SOURCE_METADATA = {
    "source1.pdf": {
        "title": "Type 2 diabetes in adults: management (NG28)",
        "publisher": "National Institute for Health and Care Excellence (NICE)",
        "url": "https://www.nice.org.uk/guidance/ng28",
        "topic": "Type 2 Diabetes",
    },
    "source2.pdf": {
        "title": "HEARTS D: Diagnosis and management of type 2 diabetes",
        "publisher": "World Health Organization (WHO)",
        "url": "https://iris.who.int/handle/10665/331710",
        "topic": "Type 2 Diabetes",
    },
}

# Default metadata used when a file in data/source is not registered in
# the dict above, so the script doesn't crash — but it prints a clear
# warning telling you to add it.
DEFAULT_METADATA = {
    "title": "UNKNOWN — add this file to SOURCE_METADATA",
    "publisher": "UNKNOWN",
    "url": "",
    "topic": "Type 2 Diabetes",
}


# =========================
# Text cleaning
# =========================

def clean_text(text: str) -> str:
    """
    Clean extracted PDF text while preserving line structure.

    Important:
    We preserve single newlines because they may represent
    headings, recommendations, lists, or section boundaries.
    """

    # Normalize line endings
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Fix common PDF ligatures
    text = text.replace("\ufb01", "fi")
    text = text.replace("\ufb02", "fl")

    # Remove hyphenation caused by line breaks
    # Example:
    # manage-
    # ment -> management
    text = re.sub(r"-\n(?=[a-z])", "", text)

    # Remove trailing spaces from lines
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)

    # Collapse excessive spaces inside lines
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Keep maximum of two consecutive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# =========================
# PDF extraction
# =========================

def extract_pdf(pdf_path: str) -> dict:
    """
    Extract text from a single PDF.

    Output format:

    {
        "source": "example.pdf",
        "title": "...",
        "publisher": "...",
        "url": "...",
        "topic": "...",
        "total_pages": 12,
        "extracted_pages": 12,
        "pages": [
            {
                "page_number": 1,
                "text": "...",
                "char_count": 1420
            }
        ]
    }
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}"
        )

    pages = []

    with fitz.open(pdf_path) as doc:

        total_pages = doc.page_count

        for page_index, page in enumerate(doc):

            raw_text = page.get_text("text")

            cleaned_text = clean_text(raw_text)

            pages.append({
                "page_number": page_index + 1,
                "text": cleaned_text,
                "char_count": len(cleaned_text)
            })

    # Look up source metadata by filename
    metadata = SOURCE_METADATA.get(pdf_path.name, DEFAULT_METADATA)
    if pdf_path.name not in SOURCE_METADATA:
        print(
            f"[warning] '{pdf_path.name}' is not registered in SOURCE_METADATA — "
            f"add it at the top of this file so title/publisher/url are not UNKNOWN."
        )

    return {
        "source": pdf_path.name,
        "title": metadata["title"],
        "publisher": metadata["publisher"],
        "url": metadata["url"],
        "topic": metadata["topic"],
        "total_pages": total_pages,
        "extracted_pages": len(pages),
        "pages": pages
    }


# =========================
# Sample page inspection
# Lets us visually confirm extraction and cleaning worked correctly
# before moving on to the chunking step.
# =========================

def inspect_sample(document: dict, n: int = 3) -> None:
    """
    Print a sample of the first n pages that contain real text
    (more than 100 characters) for manual review — not every page,
    since some are covers, blank pages, or a table of contents.
    """
    non_empty = [p for p in document["pages"] if p["char_count"] > 100]

    print(
        f"Pages with real text: {len(non_empty)} out of {document['total_pages']}"
    )
    print("-" * 50)

    for page in non_empty[:n]:
        preview = page["text"][:400].replace("\n", " ")
        print(f"[page {page['page_number']} | {page['char_count']} chars]")
        print(preview + ("..." if len(page["text"]) > 400 else ""))
        print()


# =========================
# Save JSON
# =========================

def save_json(data: dict, output_path: Path) -> None:

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


# =========================
# Process all PDFs
# =========================

def process_directory(
    source_dir: Path = SOURCE_DIR,
    output_dir: Path = OUTPUT_DIR
) -> list:

    source_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    pdf_files = sorted(
        source_dir.glob("*.pdf")
    )

    if not pdf_files:
        print(
            f"No PDF files found in: {source_dir}"
        )
        return []

    results = []

    for pdf_path in pdf_files:

        print(
            f"\nProcessing: {pdf_path.name}"
        )

        document = extract_pdf(
            pdf_path
        )

        # Inspect a sample of pages right after extraction
        inspect_sample(document, n=3)

        output_path = (
            output_dir /
            f"{pdf_path.stem}.json"
        )

        save_json(
            document,
            output_path
        )

        results.append(document)

        print(
            f"Total pages: "
            f"{document['total_pages']}"
        )

        print(
            f"Pages extracted: "
            f"{document['extracted_pages']}"
        )

        print(
            f"Saved to: "
            f"{output_path}"
        )

    return results


# =========================
# Main
# =========================

if __name__ == "__main__":

    documents = process_directory()

    total_documents = len(documents)

    total_pages = sum(
        doc["total_pages"]
        for doc in documents
    )

    total_extracted = sum(
        doc["extracted_pages"]
        for doc in documents
    )

    print("\n" + "=" * 50)

    print(
        f"Documents processed: "
        f"{total_documents}"
    )

    print(
        f"Total PDF pages: "
        f"{total_pages}"
    )

    print(
        f"Total extracted pages: "
        f"{total_extracted}"
    )

    print("=" * 50)