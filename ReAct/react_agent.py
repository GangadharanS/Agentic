"""
ReAct agent — Reason → Act → Observe loop with Gemini (cloud) + MCP tools.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

import google.generativeai as genai
from dotenv import load_dotenv

from mcp_bridge import MCPClient

load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


@dataclass
class ReActStep:
    round_num: int
    thought: str = ""
    action: str = ""
    action_input: dict = field(default_factory=dict)
    observation: str = ""


class ReActAgent:
    """Runs a multi-round ReAct loop: Gemini reasons, calls MCP tools, observes results."""

    def __init__(self, mcp_client: MCPClient, model: str | None = None):
        self.mcp = mcp_client
        self.model_name = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is required. Get a free key: https://aistudio.google.com/apikey"
            )
        genai.configure(api_key=api_key)
        self._model: Optional[genai.GenerativeModel] = None

    def is_available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY", "").strip())

    async def run(
        self,
        system_prompt: str,
        user_message: str,
        *,
        tool_filter: Optional[List[str]] = None,
        max_rounds: int = 8,
        verbose: bool = True,
    ) -> dict:
        if not self.mcp.tools:
            await self.mcp.discover_tools()

        declarations = self._tools_for_gemini(tool_filter)
        self._model = genai.GenerativeModel(
            self.model_name,
            system_instruction=system_prompt,
            tools=declarations if declarations else None,
        )

        chat = self._model.start_chat(history=[])
        steps: List[ReActStep] = []
        tool_calls_made: List[dict] = []

        response = await self._send(chat, user_message)

        for round_num in range(1, max_rounds + 1):
            step = ReActStep(round_num=round_num)
            if verbose:
                print(f"\n--- ReAct round {round_num}/{max_rounds} ---")

            if response is None:
                return {
                    "success": False,
                    "error": "Gemini request failed",
                    "text": "",
                    "steps": steps,
                    "tool_calls_made": tool_calls_made,
                }

            function_calls = self._extract_function_calls(response)
            text = self._extract_text(response)

            if text and verbose:
                step.thought = text[:500]
                print(f"Thought: {text[:300]}{'...' if len(text) > 300 else ''}")

            if not function_calls:
                step.observation = "(final answer)"
                steps.append(step)
                final_text = text or self._response_to_text(response)
                return {
                    "success": True,
                    "text": final_text,
                    "steps": steps,
                    "tool_calls_made": tool_calls_made,
                }

            for fc in function_calls:
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}

                step.action = tool_name
                step.action_input = tool_args
                tool_calls_made.append({"tool": tool_name, "arguments": tool_args})

                if verbose:
                    print(f"Action:  {tool_name}({json.dumps(tool_args)[:200]})")

                try:
                    result = await self.mcp.call_tool(tool_name, tool_args)
                    observation = self._format_observation(result)
                except Exception as exc:
                    observation = f"Tool error: {exc}"

                step.observation = observation[:500]
                if verbose:
                    print(
                        f"Observe: {observation[:400]}"
                        f"{'...' if len(observation) > 400 else ''}"
                    )

                response = await self._send_function_result(
                    chat, tool_name, {"result": observation[:8000]}
                )

            steps.append(step)

        return {
            "success": True,
            "text": "Max ReAct rounds reached.",
            "steps": steps,
            "tool_calls_made": tool_calls_made,
        }

    def _tools_for_gemini(self, tool_filter: Optional[List[str]]) -> list:
        declarations = []
        for tool in self.mcp.tools:
            name = tool["name"]
            if tool_filter and not self._matches_filter(name, tool_filter):
                continue
            schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
            declarations.append(
                {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": schema,
                }
            )
        return declarations

    @staticmethod
    def _matches_filter(name: str, patterns: List[str]) -> bool:
        for pattern in patterns:
            regex = re.escape(pattern).replace(r"\*", ".*")
            if re.fullmatch(regex, name):
                return True
        return False

    async def _send(self, chat, message: str):
        try:
            return await asyncio.to_thread(
                chat.send_message,
                message,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=8192,
                ),
            )
        except Exception as exc:
            print(f"[ReAct] Gemini error: {exc}")
            return None

    async def _send_function_result(self, chat, name: str, response_payload: dict):
        try:
            return await asyncio.to_thread(
                chat.send_message,
                {
                    "role": "function",
                    "parts": [
                        {
                            "function_response": {
                                "name": name,
                                "response": response_payload,
                            }
                        }
                    ],
                },
            )
        except Exception as exc:
            print(f"[ReAct] Gemini function response error: {exc}")
            return None

    @staticmethod
    def _extract_function_calls(response) -> list:
        calls = []
        if not response or not response.candidates:
            return calls
        for part in response.candidates[0].content.parts:
            if part.function_call and part.function_call.name:
                calls.append(part.function_call)
        return calls

    @staticmethod
    def _extract_text(response) -> str:
        if not response or not response.candidates:
            return ""
        texts = []
        for part in response.candidates[0].content.parts:
            if part.text:
                texts.append(part.text)
        return "\n".join(texts).strip()

    @staticmethod
    def _response_to_text(response) -> str:
        try:
            return response.text or ""
        except Exception:
            return ReActAgent._extract_text(response)

    @staticmethod
    def _format_observation(result: dict) -> str:
        if not result:
            return "No result"
        if result.get("success") and "data" in result:
            data = result["data"]
            if isinstance(data, dict) and "content" in data:
                parts = []
                for item in data["content"]:
                    if isinstance(item, dict):
                        parts.append(item.get("text", str(item)))
                    else:
                        parts.append(str(item))
                return "\n".join(parts)
            return json.dumps(data, indent=2) if isinstance(data, dict) else str(data)
        if "error" in result:
            return f"Error: {result['error']}"
        return json.dumps(result, indent=2)


def parse_json_from_text(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
