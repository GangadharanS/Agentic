import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import List

import chromadb
from langchain.schema import Document
from pinecone import Pinecone, ServerlessSpec

from app.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    DEFAULT_COLLECTION,
    EMBEDDING_DIMENSION,
    PINECONE_API_KEY,
    PINECONE_AUTO_RECREATE_INDEX,
    PINECONE_CLOUD,
    PINECONE_INDEX_NAME,
    PINECONE_REGION,
    RAG_MODE,
)


logger = logging.getLogger(__name__)


class VectorStore(ABC):
    @abstractmethod
    def ingest(
        self,
        chunks: List[Document],
        embeddings: List[List[float]],
        collection_name: str,
    ) -> int:
        pass

    @abstractmethod
    def search(
        self,
        query_embedding: List[float],
        collection_name: str,
        top_k: int,
    ) -> tuple[List[str], List[dict], List[float]]:
        pass

    @abstractmethod
    def list_collections(self) -> List[dict]:
        pass

    @abstractmethod
    def delete_collection(self, name: str) -> bool:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class ChromaVectorStore(VectorStore):
    def __init__(self):
        self._client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

    @property
    def name(self) -> str:
        return "chromadb"

    def _get_collection(self, name: str = DEFAULT_COLLECTION):
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine", "embedding_dimension": EMBEDDING_DIMENSION},
        )

    def _ensure_collection_dim(self, name: str, dim: int):
        """Recreate the collection if its stored dimension doesn't match."""
        collection = self._get_collection(name)
        stored_dim = (collection.metadata or {}).get("embedding_dimension")
        if stored_dim is None and collection.count() == 0:
            return collection
        if stored_dim is not None and stored_dim != dim:
            logger.warning(
                "Chroma collection '%s' dimension mismatch (existing=%s, "
                "required=%d). Recreating — all stored vectors in this "
                "collection will be lost.",
                name,
                stored_dim,
                dim,
            )
            self._client.delete_collection(name)
            collection = self._get_collection(name)
        return collection

    def ingest(
        self,
        chunks: List[Document],
        embeddings: List[List[float]],
        collection_name: str,
    ) -> int:
        dim = len(embeddings[0]) if embeddings else EMBEDDING_DIMENSION
        collection = self._ensure_collection_dim(collection_name, dim)
        texts = [chunk.page_content for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]
        ids = [str(uuid.uuid4()) for _ in chunks]

        batch_size = 100
        total_stored = 0
        for i in range(0, len(texts), batch_size):
            collection.add(
                documents=texts[i : i + batch_size],
                embeddings=embeddings[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
                ids=ids[i : i + batch_size],
            )
            total_stored += len(texts[i : i + batch_size])
        return total_stored

    def search(
        self,
        query_embedding: List[float],
        collection_name: str,
        top_k: int,
    ) -> tuple[List[str], List[dict], List[float]]:
        collection = self._get_collection(collection_name)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return documents, metadatas, distances

    def list_collections(self) -> List[dict]:
        collections = self._client.list_collections()
        result = []
        for col in collections:
            count = self._client.get_collection(col.name).count()
            result.append({"name": col.name, "document_count": count})
        return result

    def delete_collection(self, name: str) -> bool:
        try:
            self._client.delete_collection(name)
            return True
        except Exception:
            return False

    def health_check(self) -> bool:
        try:
            self._client.heartbeat()
            return True
        except Exception:
            return False


class PineconeVectorStore(VectorStore):
    def __init__(self):
        if not PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY is required when RAG_MODE=cloud")
        self._pc = Pinecone(api_key=PINECONE_API_KEY)
        self._ensure_index()
        self._index = self._pc.Index(PINECONE_INDEX_NAME)

    @property
    def name(self) -> str:
        return "pinecone"

    def _ensure_index(self):
        existing = {index.name for index in self._pc.list_indexes()}

        if PINECONE_INDEX_NAME in existing:
            description = self._pc.describe_index(PINECONE_INDEX_NAME)
            current_dim = getattr(description, "dimension", None)
            if current_dim and current_dim != EMBEDDING_DIMENSION:
                if not PINECONE_AUTO_RECREATE_INDEX:
                    raise ValueError(
                        f"Pinecone index '{PINECONE_INDEX_NAME}' has dimension "
                        f"{current_dim}, but the configured embedding dimension "
                        f"is {EMBEDDING_DIMENSION}. Either change "
                        f"PINECONE_INDEX_NAME to a new name, or set "
                        f"PINECONE_AUTO_RECREATE_INDEX=true to delete the existing "
                        f"index and recreate it (will erase all stored vectors)."
                    )
                logger.warning(
                    "Pinecone index '%s' dimension mismatch (existing=%d, "
                    "required=%d). Deleting and recreating — all stored vectors "
                    "will be lost. Re-ingest your documents after restart.",
                    PINECONE_INDEX_NAME,
                    current_dim,
                    EMBEDDING_DIMENSION,
                )
                self._pc.delete_index(PINECONE_INDEX_NAME)
                self._wait_until_index_absent()
            else:
                return

        self._pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=EMBEDDING_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
        )
        self._wait_until_index_ready()

    def _wait_until_index_absent(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            existing = {index.name for index in self._pc.list_indexes()}
            if PINECONE_INDEX_NAME not in existing:
                return
            time.sleep(1.0)

    def _wait_until_index_ready(self, timeout: float = 120.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                description = self._pc.describe_index(PINECONE_INDEX_NAME)
                if getattr(description.status, "ready", False):
                    return
            except Exception:
                pass
            time.sleep(1.0)

    def ingest(
        self,
        chunks: List[Document],
        embeddings: List[List[float]],
        collection_name: str,
    ) -> int:
        vectors = []
        for chunk, embedding in zip(chunks, embeddings):
            metadata = {
                "text": chunk.page_content,
                "source": str(chunk.metadata.get("source", "unknown")),
                "chunk_index": int(chunk.metadata.get("chunk_index", -1)),
            }
            vectors.append(
                {
                    "id": str(uuid.uuid4()),
                    "values": embedding,
                    "metadata": metadata,
                }
            )

        batch_size = 100
        total_stored = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            self._index.upsert(vectors=batch, namespace=collection_name)
            total_stored += len(batch)
        return total_stored

    def search(
        self,
        query_embedding: List[float],
        collection_name: str,
        top_k: int,
    ) -> tuple[List[str], List[dict], List[float]]:
        results = self._index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
            namespace=collection_name,
        )
        documents = []
        metadatas = []
        distances = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            documents.append(meta.get("text", ""))
            metadatas.append(
                {
                    "source": meta.get("source", "unknown"),
                    "chunk_index": meta.get("chunk_index", -1),
                }
            )
            distances.append(match.get("score", 0.0))
        return documents, metadatas, distances

    def list_collections(self) -> List[dict]:
        stats = self._index.describe_index_stats()
        namespaces = stats.get("namespaces") or {}
        return [
            {"name": name, "document_count": info.get("vector_count", 0)}
            for name, info in namespaces.items()
        ]

    def delete_collection(self, name: str) -> bool:
        try:
            self._index.delete(delete_all=True, namespace=name)
            return True
        except Exception:
            return False

    def health_check(self) -> bool:
        try:
            self._index.describe_index_stats()
            return True
        except Exception:
            return False


def get_vector_store() -> VectorStore:
    if RAG_MODE == "cloud":
        return PineconeVectorStore()
    return ChromaVectorStore()
