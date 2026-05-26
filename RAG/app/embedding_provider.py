import logging
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any, List, Optional

import httpx

from app.config import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    GEMINI_API_KEY,
    GEMINI_EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        pass

    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass


# ---------------------------------------------------------------------------
# Lazy-loader for sentence-transformers + torch.
#
# torch + sentence-transformers add ~600 MB to the image and are only needed
# when EMBEDDING_PROVIDER=local. Keeping them out of the base image means:
#   - cloud-mode users get a smaller, faster-to-build image
#   - local-mode users pay a one-time install cost on first request
# The install is pinned to CPU-only torch to avoid ~2 GB of CUDA wheels.
# ---------------------------------------------------------------------------
_SentenceTransformerCls: Optional[type] = None

_TORCH_VERSION = "torch==2.4.1+cpu"
_TORCH_INDEX_URL = "https://download.pytorch.org/whl/cpu"
_SENTENCE_TRANSFORMERS_VERSION = "sentence-transformers==3.1.1"


def _pip_install(args: List[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", *args]
    logger.info("Running: %s", " ".join(cmd))
    subprocess.check_call(cmd)


def _load_sentence_transformer_cls() -> type:
    """Import SentenceTransformer, installing torch + sentence-transformers on demand."""
    global _SentenceTransformerCls
    if _SentenceTransformerCls is not None:
        return _SentenceTransformerCls

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _SentenceTransformerCls = SentenceTransformer
        return _SentenceTransformerCls
    except ImportError:
        logger.warning(
            "sentence-transformers not installed. Installing CPU-only torch + "
            "sentence-transformers now. This is a one-time ~2-5 min operation "
            "(triggered because EMBEDDING_PROVIDER=local). To avoid this delay, "
            "set EMBEDDING_PROVIDER=gemini, or pre-install the packages by "
            "adding them to the Dockerfile (see requirements-local.txt)."
        )

    _pip_install([_TORCH_VERSION, "--index-url", _TORCH_INDEX_URL])
    _pip_install([_SENTENCE_TRANSFORMERS_VERSION])

    from sentence_transformers import SentenceTransformer  # type: ignore
    _SentenceTransformerCls = SentenceTransformer
    logger.info("sentence-transformers installed and imported successfully.")
    return _SentenceTransformerCls


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self._model: Optional[Any] = None

    @property
    def name(self) -> str:
        return "sentence_transformers"

    @property
    def model(self) -> Any:
        if self._model is None:
            cls = _load_sentence_transformer_cls()
            self._model = cls(EMBEDDING_MODEL)
        return self._model

    @property
    def dimension(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode(texts, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode([text], show_progress_bar=False)[0].tolist()

    def health_check(self) -> bool:
        try:
            _ = self.model
            return True
        except Exception:
            return False


# Natural (default) output dimensions per Gemini embedding model.
# Reference: https://ai.google.dev/gemini-api/docs/embeddings
_GEMINI_NATURAL_DIMENSIONS = {
    "text-embedding-004": 768,  # legacy, retired on Jan 14, 2026 — returns 404
    "gemini-embedding-001": 3072,  # GA; supports Matryoshka 768 / 1536 / 3072
    "gemini-embedding-2-preview": 3072,  # preview, multimodal
}

# Models that support the `outputDimensionality` parameter for Matryoshka
# truncation. Sending this on unsupported models causes a 400.
_GEMINI_MATRYOSHKA_MODELS = {"gemini-embedding-001"}


class GeminiEmbeddingProvider(EmbeddingProvider):
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini"
            )
        self._model = GEMINI_EMBEDDING_MODEL
        natural = _GEMINI_NATURAL_DIMENSIONS.get(self._model, 768)
        # Use EMBEDDING_DIMENSION if it differs from the model's natural dim
        # (only valid for Matryoshka-capable models, otherwise we ignore it).
        self._dimension = EMBEDDING_DIMENSION or natural
        self._supports_output_dim = self._model in _GEMINI_MATRYOSHKA_MODELS

    @property
    def name(self) -> str:
        return "gemini_embedding"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _build_request(self, text: str, task_type: str) -> dict:
        item = {
            "model": f"models/{self._model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
        }
        # Only send outputDimensionality when the model supports it AND the
        # configured dimension differs from the model's natural size.
        natural = _GEMINI_NATURAL_DIMENSIONS.get(self._model, 768)
        if self._supports_output_dim and self._dimension != natural:
            item["outputDimensionality"] = self._dimension
        return item

    def _embed(self, texts: List[str], task_type: str) -> List[List[float]]:
        # Use batch endpoint to embed multiple texts in one HTTP call.
        url = f"{self._BASE_URL}/models/{self._model}:batchEmbedContents"
        payload = {
            "requests": [self._build_request(text, task_type) for text in texts]
        }
        response = httpx.post(
            url,
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        return [item["values"] for item in data.get("embeddings", [])]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        results: List[List[float]] = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            results.extend(
                self._embed(texts[i : i + batch_size], "RETRIEVAL_DOCUMENT")
            )
        return results

    def embed_query(self, text: str) -> List[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]

    def health_check(self) -> bool:
        try:
            response = httpx.get(
                f"{self._BASE_URL}/models/{self._model}",
                params={"key": GEMINI_API_KEY},
                timeout=10.0,
            )
            return response.status_code == 200
        except Exception:
            return False


def get_embedding_provider() -> EmbeddingProvider:
    if EMBEDDING_PROVIDER == "gemini":
        return GeminiEmbeddingProvider()
    return LocalEmbeddingProvider()
