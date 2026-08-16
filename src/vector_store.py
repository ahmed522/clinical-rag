import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent if "__file__" in locals() else Path.cwd()
SOURCE_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "data" / "embeddings"
DB_DIR = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "documents"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------
@dataclass
class EmbeddedChunk:
    chunk_id: str
    source: str
    page_number: int
    text: str
    embedding: list[float]

# ---------------------------------------------------------------------------
# Embedding Pipeline
# ---------------------------------------------------------------------------
class EmbeddingPipeline:
    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        device: str | None = None,
        batch_size: int = 32,
    ):
        self.model = SentenceTransformer(model_name, device=device)[cite: 2]
        self.batch_size = batch_size[cite: 2]
        self.model_name = model_name[cite: 2]

    def embed_chunks(self, chunks: list[dict]) -> list[EmbeddedChunk]:
        texts = [c["text"] for c in chunks][cite: 2]

        # Batch encode with normalization for cosine metric alignment
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[cite: 2]

        embedded_chunks = []
        for chunk, emb in zip(chunks, embeddings):
            embedded_chunks.append(
                EmbeddedChunk(
                    chunk_id=chunk["chunk_id"],
                    source=chunk["source"],
                    page_number=chunk["page_number"],
                    text=chunk["text"],
                    embedding=emb.tolist(),
                )
            )[cite: 2]
        return embedded_chunks[cite: 2]

# ---------------------------------------------------------------------------
# Vector Store Manager
# ---------------------------------------------------------------------------
class VectorStore:
    def __init__(
        self,
        pipeline: EmbeddingPipeline | None = None,
        db_dir: Path | str = DB_DIR,
        collection_name: str = COLLECTION_NAME,
    ):
        # Share model instance to eliminate duplicate memory loads
        self.pipeline = pipeline or EmbeddingPipeline()
        self.client = chromadb.PersistentClient(path=str(db_dir))[cite: 1]
        self.collection = self.client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )[cite: 1]

    def add_embedded_chunks(self, embedded_chunks: list[EmbeddedChunk], batch_size: int = 500):
        """Directly inserts pre-computed embeddings & complete metadata to bypass re-encoding."""
        if not embedded_chunks:
            return

        for i in range(0, len(embedded_chunks), batch_size):
            batch = embedded_chunks[i : i + batch_size]

            ids = [c.chunk_id for c in batch]
            documents = [c.text for c in batch]
            embeddings = [c.embedding for c in batch]
            metadatas = [
                {
                    "source": c.source,
                    "page_number": c.page_number,
                }
                for c in batch
            ]

            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )[cite: 1]

    def search(self, query: str, top_k: int = 5):
        query_embedding = self.pipeline.model.encode(
            [query], normalize_embeddings=True
        )[0].tolist()[cite: 1]

        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )[cite: 1]

    def count(self) -> int:
        return self.collection.count()[cite: 1]

# ---------------------------------------------------------------------------
# Helper Utility Functions
# ---------------------------------------------------------------------------
def load_chunks(chunks_path: Path | str) -> list[dict]:
    with open(chunks_path, "r", encoding="utf-8") as f:
        data = json.load(f)[cite: 2]
    return data if isinstance(data, list) else data["chunks"][cite: 2]

def save_embeddings_json(embedded_chunks: list[EmbeddedChunk], out_path: Path | str, model_name: str):
    output = {
        "model": model_name,
        "embedding_dim": len(embedded_chunks[0].embedding) if embedded_chunks else 0,
        "count": len(embedded_chunks),
        "chunks": [asdict(c) for c in embedded_chunks],
    }[cite: 2]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)[cite: 2]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)[cite: 2]

def save_embeddings_npy(embedded_chunks: list[EmbeddedChunk], out_dir: Path | str):
    os.makedirs(out_dir, exist_ok=True)[cite: 2]
    vectors = np.array([c.embedding for c in embedded_chunks], dtype=np.float32)[cite: 2]
    np.save(os.path.join(out_dir, "vectors.npy"), vectors)[cite: 2]

    metadata = [
        {
            "chunk_id": c.chunk_id,
            "source": c.source,
            "page_number": c.page_number,
            "text": c.text,
        }
        for c in embedded_chunks
    ][cite: 2]
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)[cite: 2]

# ---------------------------------------------------------------------------
# Execution Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    CHUNKS_PATH = SOURCE_DIR / "chunks.json"[cite: 2]
    OUT_JSON = OUTPUT_DIR / "embedded_chunks.json"[cite: 2]
    OUT_NPY_DIR = OUTPUT_DIR / "vector_store"[cite: 2]

    # 1. Initialize embedding engine (loads Transformer model once into memory)
    pipeline = EmbeddingPipeline(model_name=EMBEDDING_MODEL)

    # 2. Load raw dataset
    chunks = load_chunks(CHUNKS_PATH)

    # 3. Generate embeddings with normalized batching
    embedded_chunks = pipeline.embed_chunks(chunks)

    # 4. Save local backup artifacts
    save_embeddings_json(embedded_chunks, OUT_JSON, pipeline.model_name)
    save_embeddings_npy(embedded_chunks, OUT_NPY_DIR)

    # 5. Store embeddings and metadata into ChromaDB without re-computing vectors
    vector_store = VectorStore(pipeline=pipeline)
    vector_store.add_embedded_chunks(embedded_chunks)

    print(f"Successfully ingested {vector_store.count()} vectors into ChromaDB.")
