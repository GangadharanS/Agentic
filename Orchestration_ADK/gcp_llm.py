"""GCP Gemini client for the ADK orchestrator's deterministic LLM tasks.

Uses the unified **google-genai** SDK so the same code targets either:

  1. **Vertex AI** (true GCP) — set ``GOOGLE_GENAI_USE_VERTEXAI=TRUE`` plus
     ``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_CLOUD_LOCATION`` and authenticate with
     ``gcloud auth application-default login``.
  2. **Google AI Studio** — set ``GOOGLE_API_KEY`` (or ``GEMINI_API_KEY``).

This powers the Fixer (file rewrites), the Init brief, and the Pusher summary.
The Reviewer reuses ReAct's PRReviewAgent (its own ReAct loop) — see
``agents/reviewer_agent.py``.
"""
from __future__ import annotations

import asyncio
import os

try:
    from google import genai
    from google.genai import types

    _HAS_GENAI = True
except ImportError:  # pragma: no cover - import guard for first-time setup
    _HAS_GENAI = False

DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_SLM = "gemini-2.5-flash-lite"


def use_vertex() -> bool:
    return os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().upper() in {"1", "TRUE", "YES"}


def _api_key() -> str:
    return (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()


def _client():
    if not _HAS_GENAI:
        raise RuntimeError(
            "google-genai is not installed. Run: pip install google-genai"
        )
    if use_vertex():
        return genai.Client(
            vertexai=True,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    return genai.Client(api_key=_api_key())


def slm_enabled() -> bool:
    if os.getenv("ORCH_USE_SLM", "true").lower() in {"0", "false", "no"}:
        return False
    return use_vertex() or bool(_api_key())


def slm_model(env_var: str, fallback: str = DEFAULT_SLM) -> str:
    return (os.getenv(env_var, fallback) or fallback).strip() or fallback


def llm_available() -> bool:
    return _HAS_GENAI and (use_vertex() or bool(_api_key()))


async def generate_text(
    *,
    model_name: str,
    system_instruction: str,
    user_prompt: str,
    max_output_tokens: int = 1024,
    temperature: float = 0.2,
) -> str | None:
    """Single-shot Gemini generation via Vertex AI or AI Studio. None on failure."""
    if not llm_available():
        return None

    try:
        client = _client()
    except Exception as exc:  # pragma: no cover
        print(f"[gcp_llm] client init failed: {exc}")
        return None

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
    except Exception as exc:
        print(f"[gcp_llm] {model_name} error: {exc}")
        return None

    text = getattr(response, "text", "") or ""
    return text.strip() or None
