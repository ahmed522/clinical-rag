import json
import re
from pathlib import Path


# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = (
    BASE_DIR
    / "data"
    / "processed"
    / "preprocessed_documents.json"
)

OUTPUT_FILE = (
    BASE_DIR
    / "data"
    / "processed"
    / "chunks.json"
)


# ============================================================
# Chunking Configuration
# ============================================================

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Pages with fewer characters than this will not be chunked
MIN_TEXT_LENGTH = 100


# ============================================================
# Text Utilities
# ============================================================

def normalize_text(text):
    """
    Final light normalization before chunking.
    """

    if not text:
        return ""

    # Normalize spaces
    text = re.sub(r"[ \t]+", " ", text)

    # Normalize excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def split_into_paragraphs(text):
    """
    Split text into paragraphs while preserving meaningful content.
    """

    paragraphs = re.split(r"\n\s*\n", text)

    paragraphs = [
        paragraph.strip()
        for paragraph in paragraphs
        if paragraph.strip()
    ]

    return paragraphs


# ============================================================
# Chunk Creation
# ============================================================

def create_chunks(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    Create chunks while trying to preserve paragraph boundaries.

    The function first builds chunks from paragraphs.
    If a paragraph itself is too large, it is split further.
    """

    text = normalize_text(text)

    if not text:
        return []

    paragraphs = split_into_paragraphs(text)

    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:

        # ----------------------------------------------------
        # Normal paragraph
        # ----------------------------------------------------

        if len(paragraph) <= chunk_size:

            if not current_chunk:

                current_chunk = paragraph

            elif len(current_chunk) + len(paragraph) + 2 <= chunk_size:

                current_chunk += "\n\n" + paragraph

            else:

                chunks.append(current_chunk)

                # Add overlap from the previous chunk
                overlap_text = current_chunk[-overlap:]

                current_chunk = (
                    overlap_text
                    + "\n\n"
                    + paragraph
                )

        # ----------------------------------------------------
        # Very large paragraph
        # ----------------------------------------------------

        else:

            # Save current chunk first
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            start = 0

            while start < len(paragraph):

                end = start + chunk_size

                piece = paragraph[start:end]

                chunks.append(piece.strip())

                start = end - overlap

    # --------------------------------------------------------
    # Last chunk
    # --------------------------------------------------------

    if current_chunk:
        chunks.append(current_chunk.strip())

    # Remove empty chunks
    chunks = [
        chunk
        for chunk in chunks
        if chunk.strip()
    ]

    return chunks


# ============================================================
# Document Processing
# ============================================================

def process_documents(data):

    all_chunks = []

    documents = data.get("documents", [])

    for document in documents:

        source = document.get("source", "unknown")

        print(f"\nProcessing: {source}")

        document_chunks = 0

        for page in document.get("pages", []):

            page_number = page.get("page_number")

            page_type = page.get(
                "page_type",
                "content"
            )

            text = page.get("text", "")

            # ------------------------------------------------
            # Skip non-content pages
            # ------------------------------------------------

            if page_type in [
                "copyright",
                "table_of_contents"
            ]:
                print(
                    f"  Page {page_number}: skipped "
                    f"({page_type})"
                )
                continue

            # ------------------------------------------------
            # Skip empty / very short pages
            # ------------------------------------------------

            if len(text.strip()) < MIN_TEXT_LENGTH:
                print(
                    f"  Page {page_number}: skipped "
                    f"(too short)"
                )
                continue

            # ------------------------------------------------
            # Create chunks
            # ------------------------------------------------

            chunks = create_chunks(text)

            for chunk_index, chunk_text in enumerate(chunks):

                chunk_id = (
                    f"{Path(source).stem}"
                    f"_page_{page_number}"
                    f"_chunk_{chunk_index}"
                )

                chunk = {
                    "chunk_id": chunk_id,
                    "source": source,
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "text": chunk_text,
                    "char_count": len(chunk_text)
                }

                all_chunks.append(chunk)

                document_chunks += 1

        print(
            f"  Chunks created: {document_chunks}"
        )

    return all_chunks


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("Clinical RAG - Chunking")
    print("=" * 60)

    # Make sure output directory exists
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Load preprocessed documents
    # --------------------------------------------------------

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    # --------------------------------------------------------
    # Create chunks
    # --------------------------------------------------------

    chunks = process_documents(data)

    # --------------------------------------------------------
    # Save chunks
    # --------------------------------------------------------

    output_data = {
        "total_chunks": len(chunks),
        "chunks": chunks
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output_data,
            f,
            ensure_ascii=False,
            indent=2
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("Chunking completed successfully!")
    print(f"Total chunks: {len(chunks)}")
    print(f"Saved to: {OUTPUT_FILE}")
    print("=" * 60)