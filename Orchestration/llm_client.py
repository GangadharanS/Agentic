"""Thin Gemini client for lightweight SLM tasks (init, pusher)."""
from __future__ import annotations

import asyncio
import os

import google.generativeai as genai

DEFAULT_SLM = "gemini-2.5-flash-lite"


def slm_model(env_var: str, fallback: str = DEFAULT_SLM) -> str:
    return os.getenv(env_var, fallback).strip() or fallback


def slm_enabled() -> bool:
    if os.getenv("ORCH_USE_SLM", "true").lower() in {"0", "false", "no"}:
        return False
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


async def generate_text(
    *,
    model_name: str,
    system_instruction: str,
    user_prompt: str,
    max_output_tokens: int = 1024,
    temperature: float = 0.2,
) -> str | None:
    """Single-shot Gemini call. Returns None if key missing or call fails."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name,
        system_instruction=system_instruction,
    )

    try:
        response = await asyncio.to_thread(
            model.generate_content,
            [user_prompt],
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ),
        )
    except Exception as exc:
        print(f"[SLM] {model_name} error: {exc}")
        return None

    text = response.text if hasattr(response, "text") else ""
    return text.strip() if text and text.strip() else None
