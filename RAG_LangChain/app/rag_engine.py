from typing import List

from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from app.config import DEFAULT_COLLECTION, TOP_K
from app.langchain_components import (
    delete_collection,
    embedding_provider_name,
    get_llm,
    get_vectorstore,
    health_check_embeddings,
    health_check_llm,
    health_check_vector_store,
    list_collections,
    llm_provider_name,
    vector_store_name,
)

RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a helpful assistant. Answer the question based only on the "
            "provided context. If the context does not contain enough information, "
            "say so honestly.",
        ),
        ("human", "Context:\n{context}\n\nQuestion: {input}"),
    ]
)


class RAGEngine:
    def __init__(self):
        self.llm = get_llm()

    def ingest_documents(
        self, chunks: List[Document], collection_name: str = DEFAULT_COLLECTION
    ) -> dict:
        vectorstore = get_vectorstore(collection_name)
        ids = vectorstore.add_documents(chunks)
        return {
            "chunks_stored": len(ids),
            "collection": collection_name,
        }

    def query(
        self,
        question: str,
        collection_name: str = DEFAULT_COLLECTION,
        top_k: int = TOP_K,
    ) -> dict:
        vectorstore = get_vectorstore(collection_name)
        retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})

        question_answer_chain = create_stuff_documents_chain(self.llm, RAG_PROMPT)
        rag_chain = create_retrieval_chain(retriever, question_answer_chain)
        result = rag_chain.invoke({"input": question})

        sources = []
        for doc in result.get("context", []):
            score = doc.metadata.get("score")
            similarity = round(float(score), 4) if score is not None else None
            entry = {
                "source": doc.metadata.get("source", "unknown"),
                "chunk_index": doc.metadata.get("chunk_index", -1),
            }
            if similarity is not None:
                entry["similarity"] = similarity
            sources.append(entry)

        if not sources:
            scored_docs = self._search_with_scores(vectorstore, question, top_k)
            for doc, score in scored_docs:
                similarity = self._normalize_score(score)
                sources.append(
                    {
                        "source": doc.metadata.get("source", "unknown"),
                        "chunk_index": doc.metadata.get("chunk_index", -1),
                        "similarity": similarity,
                    }
                )

        return {
            "question": question,
            "answer": result.get("answer", "No answer generated."),
            "sources": sources,
            "context_chunks": len(result.get("context", [])),
        }

    def _search_with_scores(self, vectorstore, question: str, top_k: int):
        if vector_store_name() == "pinecone":
            return vectorstore.similarity_search_with_score(question, k=top_k)
        return vectorstore.similarity_search_with_score(question, k=top_k)

    def _normalize_score(self, score: float) -> float:
        if vector_store_name() == "pinecone":
            return round(score, 4)
        return round(1 - score, 4)

    def list_collections(self) -> List[dict]:
        return list_collections()

    def delete_collection(self, name: str) -> bool:
        return delete_collection(name)

    async def health_check(self) -> dict:
        return {
            vector_store_name(): health_check_vector_store(),
            llm_provider_name(): health_check_llm(),
            embedding_provider_name(): health_check_embeddings(),
        }


rag_engine = RAGEngine()
