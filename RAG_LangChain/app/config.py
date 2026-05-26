import os


RAG_MODE = os.getenv("RAG_MODE", "local").lower()  # local | cloud

# Local LLM (Ollama)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "600"))

# Local vector store (ChromaDB)
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

# Cloud vector store (Pinecone)
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "rag-index")
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")
# If true, the Pinecone index is deleted and recreated when its dimension
# does not match the configured embedding dimension. DATA LOSS — re-ingest after.
PINECONE_AUTO_RECREATE_INDEX = os.getenv(
    "PINECONE_AUTO_RECREATE_INDEX", "false"
).lower() in ("1", "true", "yes")

# Cloud LLM
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()  # groq | gemini
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Embeddings
# EMBEDDING_PROVIDER: local (sentence-transformers) | gemini (cloud, free tier)
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
# NOTE: text-embedding-004 was retired by Google on Jan 14, 2026.
# gemini-embedding-001 is the current GA model. It defaults to 3072 dim but
# supports 768 / 1536 / 3072 via Matryoshka truncation (outputDimensionality).
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")


def _default_embedding_dimension() -> int:
    if EMBEDDING_PROVIDER == "gemini":
        if GEMINI_EMBEDDING_MODEL in (
            "gemini-embedding-001",
            "gemini-embedding-2-preview",
        ):
            return 3072
        return 768  # legacy text-embedding-004 fallback (retired)
    return 384  # sentence-transformers all-MiniLM-L6-v2


_embedding_dim_override = os.getenv("EMBEDDING_DIMENSION", "").strip()
EMBEDDING_DIMENSION = (
    int(_embedding_dim_override)
    if _embedding_dim_override
    else _default_embedding_dimension()
)

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

TOP_K = int(os.getenv("TOP_K", "5"))

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/data")

DEFAULT_COLLECTION = os.getenv("DEFAULT_COLLECTION", "documents")
