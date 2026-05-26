from typing import List

from langchain.schema import Document

from app.config import DEFAULT_COLLECTION, TOP_K
from app.embedding_provider import get_embedding_provider
from app.llm_provider import get_llm_provider
from app.vector_store import get_vector_store


class RAGEngine:
    def __init__(self):
        self.embeddings = get_embedding_provider()
        self.vector_store = get_vector_store()
        self.llm = get_llm_provider()

    def ingest_documents(
        self, chunks: List[Document], collection_name: str = DEFAULT_COLLECTION
    ) -> dict:
        texts = [chunk.page_content for chunk in chunks]
        embeddings = self.embeddings.embed_documents(texts)
        total_stored = self.vector_store.ingest(chunks, embeddings, collection_name)
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
        query_embedding = self.embeddings.embed_query(question)
        documents, metadatas, scores = self.vector_store.search(
            query_embedding, collection_name, top_k
        )

        context = "\n\n---\n\n".join(documents) if documents else "No relevant context found."

        sources = []
        for meta, score in zip(metadatas, scores):
            if self.vector_store.name == "pinecone":
                similarity = round(score, 4)
            else:
                similarity = round(1 - score, 4)
            sources.append(
                {
                    "source": meta.get("source", "unknown"),
                    "chunk_index": meta.get("chunk_index", -1),
                    "similarity": similarity,
                }
            )

        answer = self.llm.generate(question, context)

        return {
            "question": question,
            "answer": answer,
            "sources": sources,
            "context_chunks": len(documents),
        }

    def list_collections(self) -> List[dict]:
        return self.vector_store.list_collections()

    def delete_collection(self, name: str) -> bool:
        return self.vector_store.delete_collection(name)

    async def health_check(self) -> dict:
        return {
            self.vector_store.name: self.vector_store.health_check(),
            self.llm.name: self.llm.health_check(),
            self.embeddings.name: self.embeddings.health_check(),
        }


rag_engine = RAGEngine()
