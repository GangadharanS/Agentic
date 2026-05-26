import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import List

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.vectorstores import VectorStore
from pinecone import Pinecone, ServerlessSpec

from app.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    DEFAULT_COLLECTION,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    GEMINI_API_KEY,
    GEMINI_EMBEDDING_MODEL,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    PINECONE_API_KEY,
    PINECONE_AUTO_RECREATE_INDEX,
    PINECONE_CLOUD,
    PINECONE_INDEX_NAME,
    PINECONE_REGION,
    RAG_MODE,
)

logger = logging.getLogger(__name__)

_TORCH_VERSION = "torch==2.4.1+cpu"
_TORCH_INDEX_URL = "https://download.pytorch.org/whl/cpu"
_LOCAL_REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements-local.txt"
_local_stack_installed = False


def _pip_install(args: List[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", *args]
    logger.info("Running: %s", " ".join(cmd))
    subprocess.check_call(cmd)


def _ensure_local_stack_deps() -> None:
    """Install chromadb / ollama / huggingface LangChain integrations on demand."""
    global _local_stack_installed
    if _local_stack_installed:
        return
    try:
        import chromadb  # noqa: F401
        import langchain_chroma  # noqa: F401
    except ImportError:
        logger.warning(
            "Local stack not installed. Installing requirements-local.txt "
            "(one-time ~2-5 min, triggered by RAG_MODE=local or "
            "EMBEDDING_PROVIDER=local)."
        )
        _pip_install(["-r", str(_LOCAL_REQUIREMENTS)])
    _local_stack_installed = True


def _ensure_local_embedding_deps() -> None:
    _ensure_local_stack_deps()
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        logger.warning(
            "Installing CPU-only torch + sentence-transformers for local embeddings."
        )
        _pip_install([_TORCH_VERSION, "--index-url", _TORCH_INDEX_URL])
        _pip_install(["sentence-transformers==3.1.1"])


class _GeminiEmbeddingsWithDim(Embeddings):
    """Wraps GoogleGenerativeAIEmbeddings to pass output_dimensionality per call.

    langchain-google-genai 2.0.x ignores output_dimensionality on the constructor
    but honors it on embed_query / embed_documents — required for 768-dim Pinecone.
    """

    def __init__(self, model: str, google_api_key: str, output_dimensionality: int):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self._inner = GoogleGenerativeAIEmbeddings(
            model=model,
            google_api_key=google_api_key,
        )
        self._dim = output_dimensionality

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._inner.embed_documents(
            texts, output_dimensionality=self._dim
        )

    def embed_query(self, text: str) -> List[float]:
        return self._inner.embed_query(text, output_dimensionality=self._dim)


def get_embeddings() -> Embeddings:
    if EMBEDDING_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini")
        dim = EMBEDDING_DIMENSION
        if GEMINI_EMBEDDING_MODEL == "gemini-embedding-001" and dim != 3072:
            return _GeminiEmbeddingsWithDim(
                model=f"models/{GEMINI_EMBEDDING_MODEL}",
                google_api_key=GEMINI_API_KEY,
                output_dimensionality=dim,
            )
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=f"models/{GEMINI_EMBEDDING_MODEL}",
            google_api_key=GEMINI_API_KEY,
        )

    _ensure_local_embedding_deps()
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def get_llm() -> BaseChatModel:
    if RAG_MODE == "cloud":
        if LLM_PROVIDER == "gemini":
            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=GEMINI_MODEL,
                google_api_key=GEMINI_API_KEY,
                temperature=0.2,
            )
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is required when RAG_MODE=cloud")
        from langchain_groq import ChatGroq

        return ChatGroq(api_key=GROQ_API_KEY, model=GROQ_MODEL, temperature=0.2)

    from langchain_ollama import ChatOllama

    _ensure_local_stack_deps()
    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=OLLAMA_MODEL,
        timeout=OLLAMA_TIMEOUT,
    )


def _ensure_pinecone_index() -> None:
    if not PINECONE_API_KEY:
        raise ValueError("PINECONE_API_KEY is required when RAG_MODE=cloud")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    existing = {index.name for index in pc.list_indexes()}

    if PINECONE_INDEX_NAME in existing:
        description = pc.describe_index(PINECONE_INDEX_NAME)
        current_dim = getattr(description, "dimension", None)
        if current_dim and current_dim != EMBEDDING_DIMENSION:
            if not PINECONE_AUTO_RECREATE_INDEX:
                raise ValueError(
                    f"Pinecone index '{PINECONE_INDEX_NAME}' has dimension "
                    f"{current_dim}, but configured embedding dimension is "
                    f"{EMBEDDING_DIMENSION}."
                )
            logger.warning(
                "Recreating Pinecone index '%s' (%d -> %d). Data loss.",
                PINECONE_INDEX_NAME,
                current_dim,
                EMBEDDING_DIMENSION,
            )
            pc.delete_index(PINECONE_INDEX_NAME)
            deadline = time.time() + 60
            while time.time() < deadline:
                if PINECONE_INDEX_NAME not in {i.name for i in pc.list_indexes()}:
                    break
                time.sleep(1)
        else:
            return

    pc.create_index(
        name=PINECONE_INDEX_NAME,
        dimension=EMBEDDING_DIMENSION,
        metric="cosine",
        spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        description = pc.describe_index(PINECONE_INDEX_NAME)
        if getattr(description.status, "ready", False):
            return
        time.sleep(1)


def get_vectorstore(collection_name: str = DEFAULT_COLLECTION) -> VectorStore:
    embeddings = get_embeddings()

    if RAG_MODE == "cloud":
        _ensure_pinecone_index()
        from langchain_pinecone import PineconeVectorStore

        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX_NAME)
        return PineconeVectorStore(
            index=index,
            embedding=embeddings,
            namespace=collection_name,
        )

    from langchain_chroma import Chroma

    _ensure_local_stack_deps()
    import chromadb

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embeddings,
    )


def embedding_provider_name() -> str:
    return "gemini_embedding" if EMBEDDING_PROVIDER == "gemini" else "sentence_transformers"


def llm_provider_name() -> str:
    if RAG_MODE == "cloud":
        return LLM_PROVIDER
    return "ollama"


def vector_store_name() -> str:
    return "pinecone" if RAG_MODE == "cloud" else "chromadb"


def list_collections() -> List[dict]:
    if RAG_MODE == "cloud":
        pc = Pinecone(api_key=PINECONE_API_KEY)
        stats = pc.Index(PINECONE_INDEX_NAME).describe_index_stats()
        namespaces = stats.get("namespaces") or {}
        return [
            {"name": name, "document_count": info.get("vector_count", 0)}
            for name, info in namespaces.items()
        ]

    _ensure_local_stack_deps()
    import chromadb

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return [
        {
            "name": col.name,
            "document_count": client.get_collection(col.name).count(),
        }
        for col in client.list_collections()
    ]


def delete_collection(name: str) -> bool:
    try:
        if RAG_MODE == "cloud":
            pc = Pinecone(api_key=PINECONE_API_KEY)
            pc.Index(PINECONE_INDEX_NAME).delete(delete_all=True, namespace=name)
        else:
            _ensure_local_stack_deps()
            import chromadb

            chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT).delete_collection(name)
        return True
    except Exception:
        return False


def health_check_embeddings() -> bool:
    try:
        get_embeddings().embed_query("health")
        return True
    except Exception:
        return False


def health_check_llm() -> bool:
    try:
        if RAG_MODE == "cloud":
            if LLM_PROVIDER == "gemini":
                if not GEMINI_API_KEY:
                    return False
                response = httpx.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}",
                    params={"key": GEMINI_API_KEY},
                    timeout=10.0,
                )
                return response.status_code == 200
            if not GROQ_API_KEY:
                return False
            response = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                timeout=10.0,
            )
            return response.status_code == 200
        response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


def health_check_vector_store() -> bool:
    try:
        if RAG_MODE == "cloud":
            pc = Pinecone(api_key=PINECONE_API_KEY)
            pc.Index(PINECONE_INDEX_NAME).describe_index_stats()
        else:
            _ensure_local_stack_deps()
            import chromadb

            chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT).heartbeat()
        return True
    except Exception:
        return False
