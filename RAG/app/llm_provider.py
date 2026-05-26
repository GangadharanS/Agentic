from abc import ABC, abstractmethod

import httpx

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    RAG_MODE,
)


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, question: str, context: str) -> str:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


def _build_prompt(question: str, context: str) -> str:
    return f"""You are a helpful assistant. Answer the question based on the provided context.
If the context doesn't contain enough information, say so honestly.

Context:
{context}

Question: {question}

Answer:"""


class OllamaProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "ollama"

    def generate(self, question: str, context: str) -> str:
        prompt = _build_prompt(question, context)
        try:
            response = httpx.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=OLLAMA_TIMEOUT,
            )
            response.raise_for_status()
            return response.json().get("response", "No response from model.")
        except httpx.ConnectError:
            return "Error: Cannot connect to Ollama. Ensure the Ollama service is running."
        except Exception as e:
            return f"Error generating answer: {str(e)}"

    def health_check(self) -> bool:
        try:
            response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False


class GroqProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "groq"

    def generate(self, question: str, context: str) -> str:
        if not GROQ_API_KEY:
            return "Error: GROQ_API_KEY is not configured."
        prompt = _build_prompt(question, context)
        try:
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error generating answer: {str(e)}"

    def health_check(self) -> bool:
        if not GROQ_API_KEY:
            return False
        try:
            response = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                timeout=10.0,
            )
            return response.status_code == 200
        except Exception:
            return False


class GeminiProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "gemini"

    def generate(self, question: str, context: str) -> str:
        if not GEMINI_API_KEY:
            return "Error: GEMINI_API_KEY is not configured."
        prompt = _build_prompt(question, context)
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                params={"key": GEMINI_API_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            return f"Error generating answer: {str(e)}"

    def health_check(self) -> bool:
        if not GEMINI_API_KEY:
            return False
        try:
            response = httpx.get(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}",
                params={"key": GEMINI_API_KEY},
                timeout=10.0,
            )
            return response.status_code == 200
        except Exception:
            return False


def get_llm_provider() -> LLMProvider:
    if RAG_MODE == "cloud":
        if LLM_PROVIDER == "gemini":
            return GeminiProvider()
        return GroqProvider()
    return OllamaProvider()
