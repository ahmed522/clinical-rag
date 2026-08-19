import json
import math
import re
import sys
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

# Extracted clinical text contains characters the default Windows
# console codepage cannot encode (>=, <=, +/-, micro). Printing a page
# preview containing one raises UnicodeEncodeError mid-run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


from config import (
    EXTRACTED_DIR as OUTPUT_DIR,
    PDF_MIN_DOCUMENT_CHARS,
    PDF_MIN_TEXT_PAGE_RATIO,
    PDF_NATIVE_TEXT_MIN_CHARS,
    SOURCE_DIR,
)


# =========================
# Source metadata
#
# Provenance travels with every chunk, so an answer can cite the document
# and page a clinician can check.
#
# In the multi-tenant application this comes from the `documents` database
# row and is passed into extract_pdf() directly. The dict below only backs
# the single-tenant CLI (`python src/ingest.py`) for the two guideline
# PDFs in data/source/, keyed by exact filename.
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
# Topic is intentionally empty rather than a specialty guess: clinics
# upload guidelines from any specialty, and a wrong topic would travel
# into every chunk's metadata and every citation.
DEFAULT_METADATA = {
    "title": "UNKNOWN — add this file to SOURCE_METADATA",
    "publisher": "UNKNOWN",
    "url": "",
    "topic": "",
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


class PDFExtractionError(ValueError):
    """A valid-looking upload could not produce a safe searchable document."""

    def __init__(self, message: str, *, code: str, report: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.report = report or {}


def extraction_quality_report(document: dict) -> dict:
    """Return page-level extraction diagnostics suitable for persistence."""

    pages = document.get("pages", [])
    total_pages = int(document.get("total_pages", len(pages)) or 0)
    text_pages = [
        page for page in pages
        if int(page.get("char_count", 0) or 0) >= PDF_NATIVE_TEXT_MIN_CHARS
    ]
    empty_pages = [
        page["page_number"] for page in pages
        if int(page.get("char_count", 0) or 0) == 0
    ]
    suspected_scanned_pages = [
        page["page_number"] for page in pages
        if page.get("suspected_scanned")
    ]
    total_characters = sum(int(page.get("char_count", 0) or 0) for page in pages)
    text_page_ratio = len(text_pages) / total_pages if total_pages else 0.0

    minimum_text_pages = max(1, math.ceil(total_pages * PDF_MIN_TEXT_PAGE_RATIO))
    usable = (
        total_pages > 0
        and total_characters >= PDF_MIN_DOCUMENT_CHARS
        and len(text_pages) >= minimum_text_pages
    )

    warnings = []
    if suspected_scanned_pages:
        warnings.append(
            f"{len(suspected_scanned_pages)} page(s) appear image-only with no extractable text"
        )
    if usable and text_page_ratio < 0.5:
        warnings.append("Less than half of the PDF pages contain searchable text")

    return {
        "usable": usable,
        "total_pages": total_pages,
        "text_pages": len(text_pages),
        "empty_pages": empty_pages,
        "suspected_scanned_pages": suspected_scanned_pages,
        "total_characters": total_characters,
        "text_page_ratio": round(text_page_ratio, 4),
        "warnings": warnings,
    }


def validate_extraction(document: dict) -> dict:
    """Reject PDFs that would otherwise create an empty or misleading index."""

    report = extraction_quality_report(document)
    if report["usable"]:
        return report

    if report["suspected_scanned_pages"]:
        raise PDFExtractionError(
            "This PDF appears to contain scanned, image-only pages with no extractable "
            "text. Upload a searchable PDF instead.",
            code="insufficient_text",
            report=report,
        )

    raise PDFExtractionError(
        "The PDF did not contain enough searchable text to build a reliable index.",
        code="insufficient_text",
        report=report,
    )


def _extract_page(page) -> dict:
    """Extract one page's native text."""

    raw_text = page.get_text("text", sort=True)
    cleaned_text = clean_text(raw_text)
    native_char_count = len(cleaned_text)
    image_count = len(page.get_images(full=True))

    suspected_scanned = image_count > 0 and native_char_count < PDF_NATIVE_TEXT_MIN_CHARS

    return {
        "text": cleaned_text,
        "char_count": len(cleaned_text),
        "native_char_count": native_char_count,
        "image_count": image_count,
        "extraction_method": "native",
        "suspected_scanned": suspected_scanned,
    }

def extract_pdf(pdf_path: str, metadata: dict = None) -> dict:
    """
    Extract text from a single PDF.

    metadata carries the document's provenance — title, publisher, url,
    topic. The application passes the `documents` row here; the CLI omits
    it and falls back to the SOURCE_METADATA table above.

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

    try:
        with fitz.open(pdf_path) as doc:
            if doc.needs_pass:
                raise PDFExtractionError(
                    "Password-protected PDFs are not supported.",
                    code="encrypted_pdf",
                )

            total_pages = doc.page_count
            if total_pages == 0:
                raise PDFExtractionError(
                    "The PDF contains no pages.",
                    code="empty_pdf",
                )

            for page_index, page in enumerate(doc):
                page_result = _extract_page(page)
                pages.append({
                    "page_number": page_index + 1,
                    **page_result,
                })
    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(
            f"The uploaded file could not be parsed as a PDF: {exc}",
            code="invalid_pdf",
        ) from exc

    # Caller-supplied provenance wins. Only fall back to the filename
    # lookup when no metadata was passed, i.e. the single-tenant CLI.
    if metadata is None:
        metadata = SOURCE_METADATA.get(pdf_path.name, DEFAULT_METADATA)
        if pdf_path.name not in SOURCE_METADATA:
            print(
                f"[warning] '{pdf_path.name}' is not registered in SOURCE_METADATA — "
                f"add it at the top of this file so title/publisher/url are not UNKNOWN."
            )

    document = {
        "source": pdf_path.name,
        "title": metadata.get("title") or DEFAULT_METADATA["title"],
        "publisher": metadata.get("publisher") or DEFAULT_METADATA["publisher"],
        "url": metadata.get("url") or "",
        "topic": metadata.get("topic") or "",
        "total_pages": total_pages,
        "extracted_pages": len(pages),
        "pages": pages,
    }

    document["extraction_report"] = validate_extraction(document)
    return document


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
