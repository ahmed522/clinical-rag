import json
import re
from pathlib import Path

import fitz  # PyMuPDF


# =========================
# Project paths
# =========================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SOURCE_DIR = PROJECT_ROOT / "data" / "source"
OUTPUT_DIR = PROJECT_ROOT / "data" / "extracted"


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

    return {
        "source": pdf_path.name,
        "total_pages": total_pages,
        "extracted_pages": len(pages),
        "pages": pages
    }


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