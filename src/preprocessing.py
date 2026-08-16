import json
import re
from pathlib import Path


# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = BASE_DIR / "data" / "extracted" / "all_documents.json"
OUTPUT_FILE = BASE_DIR / "data" / "processed" / "preprocessed_documents.json"


# ============================================================
# Text Cleaning Functions
# ============================================================

def normalize_whitespace(text):
    """
    Normalize spaces and tabs while preserving paragraph structure.
    """

    # Replace tabs with spaces
    text = text.replace("\t", " ")

    # Remove spaces before newlines
    text = re.sub(r"[ ]+\n", "\n", text)

    # Remove excessive spaces
    text = re.sub(r"[ ]{2,}", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def remove_page_numbers_noise(text):
    """
    Remove isolated page numbers that are usually PDF extraction noise.
    """

    # Remove lines containing only a number
    text = re.sub(r"(?m)^\s*\d+\s*$", "", text)

    return text


def remove_dot_leaders(text):
    """
    Remove TOC dot leaders such as:

    Introduction ........................................ 9

    while keeping the actual text.
    """

    # Replace long sequences of dots/spaces
    text = re.sub(r"\.{4,}", " ", text)

    return text


def fix_common_extraction_errors(text):
    """
    Fix common PDF extraction issues without aggressively
    modifying medical terminology.
    """

    # Common missing spaces after section numbers
    text = re.sub(
        r"(\b\d+\.\d+)([A-Za-z])",
        r"\1 \2",
        text
    )

    # Common missing spaces between words.
    # Only handle a few safe/common cases.
    replacements = {
        "beforestarting": "before starting",
        "afterstarting": "after starting",
        "withtype": "with type",
        "inpeople": "in people",
        "forpeople": "for people",
        "adultswith": "adults with",
        "peoplewith": "people with",
        "riskof": "risk of",
        "typeof": "type of",
        "useof": "use of",
        "partof": "part of",
    }

    for wrong, correct in replacements.items():
        text = re.sub(
            rf"\b{wrong}\b",
            correct,
            text,
            flags=re.IGNORECASE
        )

    return text


def clean_text(text):
    """
    Main preprocessing pipeline.
    """

    if not text:
        return ""

    # 1. Basic cleanup
    text = text.replace("\u00a0", " ")

    # 2. Remove TOC dot leaders
    text = remove_dot_leaders(text)

    # 3. Remove isolated page numbers
    text = remove_page_numbers_noise(text)

    # 4. Fix common PDF extraction errors
    text = fix_common_extraction_errors(text)

    # 5. Normalize whitespace
    text = normalize_whitespace(text)

    return text


# ============================================================
# Page Filtering
# ============================================================

def is_empty_page(text):
    """
    Detect empty pages after preprocessing.
    """

    return len(text.strip()) == 0


def is_probably_copyright_page(text):
    """
    Detect pages that mainly contain copyright / licensing information.
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


def is_probably_toc_page(text):
    """
    Detect pages that are likely Table of Contents pages.

    This is intentionally conservative.
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

    # A page containing several TOC indicators
    # is probably a contents page.
    return matches >= 2


# ============================================================
# Document Processing
# ============================================================

def process_documents(data):
    """
    Process all documents inside all_documents.json.
    """

    processed_documents = []

    documents = data.get("documents", [])

    for document in documents:

        source = document.get("source", "unknown")

        print(f"\nProcessing: {source}")

        processed_pages = []

        for page in document.get("pages", []):

            page_number = page.get("page_number")
            original_text = page.get("text", "")

            cleaned_text = clean_text(original_text)

            # Skip completely empty pages
            if is_empty_page(cleaned_text):
                continue

            page_type = "content"

            if is_probably_copyright_page(cleaned_text):
                page_type = "copyright"

            elif is_probably_toc_page(cleaned_text):
                page_type = "table_of_contents"

            processed_page = {
                "page_number": page_number,
                "page_type": page_type,
                "text": cleaned_text,
                "char_count": len(cleaned_text)
            }

            processed_pages.append(processed_page)

        processed_document = {
            "source": source,
            "total_pages": document.get("total_pages", 0),
            "processed_pages": len(processed_pages),
            "pages": processed_pages
        }

        processed_documents.append(processed_document)

        print(
            f"Original pages: {document.get('total_pages', 0)}"
        )

        print(
            f"Processed pages: {len(processed_pages)}"
        )

    return {
        "documents": processed_documents
    }


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("Clinical RAG - Text Preprocessing")
    print("=" * 60)

    # Make sure output directory exists
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # Load extracted documents
    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    # Process
    processed_data = process_documents(data)

    # Save
    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            processed_data,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("\n" + "=" * 60)
    print("Preprocessing completed successfully!")
    print(f"Saved to: {OUTPUT_FILE}")
    print("=" * 60)