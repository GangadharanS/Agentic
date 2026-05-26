import uuid
import httpx
from typing import List, Optional
from sentence_transformers import SentenceTransformer
import chromadb
from langchain.schema import Document
from app.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    CHROMA_HOST,
    CHROMA_PORT,
    EMBEDDING_MODEL,
    TOP_K,
    DEFAULT_COLLECTION,
)


class RAGEngine:
    def __init__(self):
        self._embedding_model: Optional[SentenceTransformer] = None
        self._chroma_client: Optional[chromadb.HttpClient] = None

    @property
    def embedding_model(self) -> SentenceTransformer:
        if self._embedding_model is None:
            self._embedding_model = SentenceTransformer(EMBEDDING_MODEL)
        return self._embedding_model

    @property
    def chroma_client(self) -> chromadb.HttpClient:
        if self._chroma_client is None:
            self._chroma_client = chromadb.HttpClient(
                host=CHROMA_HOST, port=CHROMA_PORT
            )
        return self._chroma_client

    def get_or_create_collection(self, name: str = DEFAULT_COLLECTION):
        return self.chroma_client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.embedding_model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def ingest_documents(
        self, chunks: List[Document], collection_name: str = DEFAULT_COLLECTION
    ) -> dict:
        """Embed and store document chunks in ChromaDB."""
        collection = self.get_or_create_collection(collection_name)

        texts = [chunk.page_content for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]
        ids = [str(uuid.uuid4()) for _ in chunks]

        batch_size = 100
        total_stored = 0

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_metadatas = metadatas[i : i + batch_size]
            batch_ids = ids[i : i + batch_size]
            batch_embeddings = self.embed_texts(batch_texts)

            collection.add(
                documents=batch_texts,
                embeddings=batch_embeddings,
                metadatas=batch_metadatas,
                ids=batch_ids,
            )
            total_stored += len(batch_texts)

        return {
            "chunks_stored": total_stored,
            "collection": collection_name,
        }

    def query(
        self,
        question: str,
        collection_name: str = DEFAULT_COLLECTION,
        top_k: int = TOP_K,
    ) -> dict:
        """Query ChromaDB for relevant chunks and generate answer via Ollama."""
        collection = self.get_or_create_collection(collection_name)

        query_embedding = self.embed_texts([question])[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        context = "\n\n---\n\n".join(documents) if documents else "No relevant context found."

        sources = []
        for meta, dist in zip(metadatas, distances):
            sources.append({
                "source": meta.get("source", "unknown"),
                "chunk_index": meta.get("chunk_index", -1),
                "similarity": round(1 - dist, 4),
            })

        answer = self._generate_answer(question, context)

        return {
            "question": question,
            "answer": answer,
            "sources": sources,
            "context_chunks": len(documents),
        }

    def _generate_answer(self, question: str, context: str) -> str:
        """Send prompt to Ollama and get a generated answer."""
        prompt = f"""You are a helpful assistant. Answer the question based on the provided context.
If the context doesn't contain enough information, say so honestly.

Context:
{context}

Question: {question}

Answer:"""

        try:
            response = httpx.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json().get("response", "No response from model.")
        except httpx.ConnectError:
            return "Error: Cannot connect to Ollama. Ensure the Ollama service is running."
        except Exception as e:
            return f"Error generating answer: {str(e)}"

    def list_collections(self) -> List[dict]:
        collections = self.chroma_client.list_collections()
        result = []
        for col in collections:
            count = self.chroma_client.get_collection(col.name).count()
            result.append({"name": col.name, "document_count": count})
        return result

    def delete_collection(self, name: str) -> bool:
        try:
            self.chroma_client.delete_collection(name)
            return True
        except Exception:
            return False

    async def health_check(self) -> dict:
        """Check connectivity to ChromaDB and Ollama."""
        status = {"chromadb": False, "ollama": False, "embedding_model": False}

        try:
            self.chroma_client.heartbeat()
            status["chromadb"] = True
        except Exception:
            pass

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                status["ollama"] = resp.status_code == 200
        except Exception:
            pass

        try:
            _ = self.embedding_model
            status["embedding_model"] = True
        except Exception:
            pass

        return status


rag_engine = RAGEngine()
