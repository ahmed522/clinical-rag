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

import json

import chromadb
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


def index_chunks(chunks, collection_name=COLLECTION_NAME, persist_dir=PERSIST_DIR):
    """
    Embed chunks and write them into ONE Chroma collection.

    Tenant safety: this only ever touches `collection_name`. It must not
    delete the persist directory — that directory holds every clinic's
    collection, so wiping it while indexing one clinic's upload would
    destroy every other clinic's vectors.

    Re-indexing is idempotent without deleting anything, because chunk
    ids are deterministic (see chunk.make_chunk_id) and Chroma upserts by
    id: re-ingesting the same document overwrites its own vectors rather
    than appending duplicates.

    Returns the number of vectors in the collection afterwards.
    """
    documents = chunks_to_documents(chunks)

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    vectorstore = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=str(persist_dir),
    )

    if documents:
        vectorstore.add_documents(
            documents=documents,
            ids=[c["chunk_id"] for c in chunks],
        )

    return vectorstore._collection.count()


def delete_collection(collection_name, persist_dir=PERSIST_DIR):
    """
    Drop a single clinic's collection, leaving all others untouched.

    Used when a document is removed or an index is rebuilt from scratch.
    """
    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(collection_name)
    except Exception:
        # Chroma raises if the collection does not exist; nothing to do.
        pass


def main():
    print("Loading chunks...")
    chunks = load_chunks()
    print(f"Number of chunks: {len(chunks)}")

    # The CLI rebuilds the single-tenant collection from scratch, so drop
    # just that collection first. Note this replaces an earlier
    # shutil.rmtree of the whole persist directory, which would now take
    # every clinic's vectors with it.
    print(f"Resetting collection '{COLLECTION_NAME}'...")
    delete_collection(COLLECTION_NAME)

    print(f"Loading embedding model: {EMBEDDING_MODEL} (first run takes longer)...")
    print("Indexing into ChromaDB...")
    count = index_chunks(chunks, COLLECTION_NAME, PERSIST_DIR)

    print(f"Stored {count} vectors in: {PERSIST_DIR} (collection: {COLLECTION_NAME})")
    print("The index is ready — you can now use it in query.py for retrieval.")


if __name__ == "__main__":
    main()