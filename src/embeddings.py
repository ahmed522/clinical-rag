import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SOURCE_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "data" / "embeddings"

@dataclass
class EmbeddedChunk:
    chunk_id: str
    source: str
    page_number: int
    text: str
    embedding: list[float]

class EmbeddingPipeline:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
                 device: str | None = None, batch_size: int = 32):
        self.model = SentenceTransformer(model_name, device=device)
        self.batch_size = batch_size
        self.model_name = model_name

    def embed_chunks(self, chunks: list[dict]) -> list[EmbeddedChunk]:
        texts = [c["text"] for c in chunks]

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,   # cosine similarity ready
            convert_to_numpy=True
        )

        embedded_chunks = []
        for chunk, emb in zip(chunks, embeddings):
            embedded_chunks.append(EmbeddedChunk(
                chunk_id=chunk["chunk_id"],
                source=chunk["source"],
                page_number=chunk["page_number"],
                text=chunk["text"],
                embedding=emb.tolist()
            ))
        return embedded_chunks

def load_chunks(chunks_path: str) -> list[dict]:
    with open(chunks_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # supports either a flat list of chunks or {"chunks": [...]}
    return data if isinstance(data, list) else data["chunks"]

def save_embeddings(embedded_chunks: list[EmbeddedChunk], out_path: str, model_name: str):
    output = {
        "model": model_name,
        "embedding_dim": len(embedded_chunks[0].embedding) if embedded_chunks else 0,
        "count": len(embedded_chunks),
        "chunks": [asdict(c) for c in embedded_chunks]
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

def save_embeddings_npy(embedded_chunks: list[EmbeddedChunk], out_dir: str):
    """Separate vectors (npy) + metadata (json) — faster to load for vector DB ingestion."""
    os.makedirs(out_dir, exist_ok=True)
    vectors = np.array([c.embedding for c in embedded_chunks], dtype=np.float32)
    np.save(os.path.join(out_dir, "vectors.npy"), vectors)

    metadata = [{
        "chunk_id": c.chunk_id,
        "source": c.source,
        "page_number": c.page_number,
        "text": c.text
    } for c in embedded_chunks]
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    CHUNKS_PATH = SOURCE_DIR / "chunks.json"
    OUT_JSON = OUTPUT_DIR / "embedded_chunks.json"
    OUT_NPY_DIR = OUTPUT_DIR / "vector_store"

    chunks = load_chunks(CHUNKS_PATH)
    pipeline = EmbeddingPipeline(model_name="sentence-transformers/all-MiniLM-L6-v2")
    embedded = pipeline.embed_chunks(chunks)

    save_embeddings(embedded, OUT_JSON, pipeline.model_name)
    save_embeddings_npy(embedded, OUT_NPY_DIR)

    print(f"Embedded {len(embedded)} chunks | dim={len(embedded[0].embedding)}")