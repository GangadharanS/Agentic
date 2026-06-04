"""Shared helpers for decoding GitHub MCP tool responses + emitting ADK events."""
from __future__ import annotations

import base64
import json
from typing import Any

try:
    from google.adk.events import Event
    from google.genai import types

    _HAS_ADK = True
except ImportError:  # pragma: no cover - allows syntax import without ADK installed
    _HAS_ADK = False
    Event = object  # type: ignore
    types = None  # type: ignore


def extract_text(value: Any) -> str:
    """MCP results come back as str, {content:[{text}]}, or arbitrary dicts."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "content" in value and isinstance(value["content"], list):
            parts = []
            for item in value["content"]:
                if isinstance(item, dict):
                    if "text" in item:
                        parts.append(item["text"])
                    elif "value" in item:
                        parts.append(str(item["value"]))
            return "\n".join(parts) if parts else json.dumps(value)
        return json.dumps(value)
    return str(value)


def parse_json(raw: Any) -> Any:
    try:
        return json.loads(extract_text(raw))
    except json.JSONDecodeError:
        return None


def parse_json_obj(raw: Any) -> dict | None:
    obj = parse_json(raw)
    if isinstance(obj, list) and obj:
        obj = obj[0]
    return obj if isinstance(obj, dict) else None


def parse_get_file_contents(raw: Any) -> tuple[str, str] | None:
    """Return (decoded_content, sha) from a get_file_contents response."""
    obj = parse_json(raw)
    if isinstance(obj, list) and obj:
        obj = obj[0]
    if not isinstance(obj, dict):
        return None
    sha = obj.get("sha", "")
    content = obj.get("content", "")
    if obj.get("encoding") == "base64" and content:
        try:
            content = base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            pass
    return (content or "", sha)


def log_event(author: str, message: str):
    """Build a simple ADK text Event so progress shows up in the run stream."""
    if not _HAS_ADK:
        return None
    return Event(
        author=author,
        content=types.Content(role="model", parts=[types.Part(text=message)]),
    )
