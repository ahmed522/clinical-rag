"""
embed_index.py
--------------
Goal: take the chunks produced by chunk.py and create embeddings
(a numeric/vector representation of each text chunk), then store them
in ChromaDB so we can do semantic search (search by meaning, not just
keyword matching).

Embedding model used: sentence-transformers/all-MiniLM-L6-v2
- Small, fast, and good enough for prototyping and a hackathon.
- For higher accuracy on clinical text specifically, you could swap it
  for a clinical-domain model like "pritamdeka/S-PubMedBert-MS-MARCO",
  but it will be slower and heavier to download.

Run with:
    python src/embed_index.py
"""

from pathlib import Path
import json
import shutil

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from config import (
    CHROMA_DIR,
    CHUNKS_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
)

PERSIST_DIR = str(CHROMA_DIR)  # Chroma wants a string, not a Path


def load_chunks() -> list[dict]:
    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def chunks_to_documents(chunks: list[dict]) -> list[Document]:
    """
    Convert each chunk (dict) into a LangChain Document, since Chroma
    expects this shape: page_content (the text) + metadata (everything
    else).

    Note: every value in metadata must be a simple str/int/float/bool,
    not a list or nested dict, or Chroma will complain.
    """
    documents = []
    for c in chunks:
        doc = Document(
            page_content=c["text"],
            metadata={
                "chunk_id": c["chunk_id"],
                "section_title": c["section_title"],
                "page_number": c["page_number"],
                "source": c["source"],
                "title": c["title"],
                "publisher": c["publisher"],
                "url": c["url"],
                "topic": c["topic"],
            },
        )
        documents.append(doc)
    return documents


def main():
    print("Loading chunks...")
    chunks = load_chunks()
    print(f"Number of chunks: {len(chunks)}")

    documents = chunks_to_documents(chunks)

    # Important: if we don't clear the old index first, running this
    # script again will APPEND the same chunks on top of the existing
    # ones instead of replacing them, causing duplicate vectors and
    # duplicate (identical) results at query time.
    if Path(PERSIST_DIR).exists():
        print(f"Removing existing index at {PERSIST_DIR} to avoid duplicates...")
        shutil.rmtree(PERSIST_DIR)

    print(f"Loading embedding model: {EMBEDDING_MODEL} (first run takes longer)...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    print("Indexing into ChromaDB...")
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=PERSIST_DIR,
        ids=[c["chunk_id"] for c in chunks],
    )

    count = vectorstore._collection.count()
    print(f"Stored {count} vectors in: {PERSIST_DIR} (collection: {COLLECTION_NAME})")
    print("The index is ready — you can now use it in query.py for retrieval.")


if __name__ == "__main__":
    main()