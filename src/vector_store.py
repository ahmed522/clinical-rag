import chromadb
from sentence_transformers import SentenceTransformer

from config import DB_DIR, COLLECTION_NAME, EMBEDDING_MODEL


class VectorStore:
    def __init__(self):
        self.model = SentenceTransformer(EMBEDDING_MODEL)

        self.client = chromadb.PersistentClient(
            path=str(DB_DIR)
        )

        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    def add_chunks(self, chunks):
        if not chunks:
            return

        texts = [item["text"] for item in chunks]
        ids = [item["id"] for item in chunks]
        metadatas = [item["metadata"] for item in chunks]

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True
        ).tolist()

        self.collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings
        )

    def search(self, query, top_k=5):
        query_embedding = self.model.encode(
            [query],
            normalize_embeddings=True
        )[0].tolist()

        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )

    def count(self):
        return self.collection.count()
