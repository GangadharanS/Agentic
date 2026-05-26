"""
Ollama Agent - Local LLM orchestrator with MCP tool calling.
Uses Llama 3 (or any Ollama model) to intelligently select and call MCP tools.
Ollama is REQUIRED -- the app will not start without it.
"""
import json
import os
import asyncio
import re
import aiohttp
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

from mcp_client import mcp_client

REQUEST_TIMEOUT = 300


class OllamaAgent:
    def __init__(self):
        self.model = os.getenv("OLLAMA_MODEL", "llama3")
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._available = None

    async def is_available(self) -> bool:
        """Check if Ollama is running and the model is loaded."""
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.base_url}/api/tags") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        model_names = [m.get("name", "") for m in data.get("models", [])]
                        short_names = [n.split(":")[0] for n in model_names]
                        self._available = (
                            self.model in short_names
                            or f"{self.model}:latest" in model_names
                        )
                        if not self._available:
                            print(f"[Ollama] Model '{self.model}' not found. Available: {short_names}")
                        return self._available
        except Exception as e:
            print(f"[Ollama] Not available: {e}")
            self._available = False
            return False

    async def require_available(self):
        """Raise RuntimeError if Ollama is not available. Call at startup."""
        if not await self.is_available():
            raise RuntimeError(
                f"Ollama is REQUIRED but not available. "
                f"Ensure 'ollama serve' is running at {self.base_url} "
                f"and model '{self.model}' is pulled."
            )

    def _mcp_tools_to_ollama_format(self, tool_filter: Optional[List[str]] = None) -> list:
        """
        Convert MCP tool schemas to Ollama/OpenAI function-calling format.
        If tool_filter is provided, only include tools whose names match
        any of the filter patterns (supports * wildcards).
        """
        tools = []
        for tool in mcp_client.tools:
            name = tool["name"]
            if tool_filter and not self._matches_filter(name, tool_filter):
                continue
            schema = tool.get("inputSchema", {"type": "object", "properties": {}})
            clean_schema = {
                "type": schema.get("type", "object"),
                "properties": schema.get("properties", {}),
                "required": schema.get("required", [])
            }
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", ""),
                    "parameters": clean_schema
                }
            })
        return tools

    @staticmethod
    def _matches_filter(name: str, patterns: List[str]) -> bool:
        for pattern in patterns:
            regex = re.escape(pattern).replace(r"\*", ".*")
            if re.fullmatch(regex, name):
                return True
        return False

    async def run(self, system_prompt: str, user_message: str,
                  max_tool_rounds: int = 5, response_format: Optional[dict] = None,
                  tool_filter: Optional[List[str]] = None) -> dict:
        """
        Agentic tool-use loop:
        1. Send system prompt + user message + available tools to Ollama
        2. If the model returns tool_calls, execute them via MCP
        3. Feed results back to the model
        4. Repeat until the model produces a final text response

        tool_filter: optional list of tool name patterns (supports * wildcards)
                     to limit which MCP tools are exposed to the LLM.
        """
        if not mcp_client.tools:
            await mcp_client.discover_tools()

        tools = self._mcp_tools_to_ollama_format(tool_filter)
        if tool_filter:
            print(f"[Ollama] Filtered to {len(tools)} tools (from {len(mcp_client.tools)})")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        tool_calls_made = []

        for round_num in range(max_tool_rounds):
            print(f"[Ollama] Round {round_num + 1}/{max_tool_rounds}")

            response = await self._chat(messages, tools, response_format)
            if response is None:
                return {"success": False, "error": "Ollama request failed", "text": ""}

            message = response.get("message", {})
            tool_calls = message.get("tool_calls", [])

            if not tool_calls:
                return {
                    "success": True,
                    "text": message.get("content", ""),
                    "tool_calls_made": tool_calls_made
                }

            messages.append(message)

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_args = func.get("arguments", {})

                print(f"[Ollama] Calling tool: {tool_name}({json.dumps(tool_args)[:200]})")
                tool_calls_made.append({"tool": tool_name, "arguments": tool_args})

                try:
                    result = await mcp_client.call_tool(tool_name, tool_args)
                    result_text = self._extract_tool_result_text(result)
                except Exception as e:
                    result_text = f"Tool error: {str(e)}"
                    print(f"[Ollama] Tool '{tool_name}' failed: {e}")

                messages.append({
                    "role": "tool",
                    "content": result_text[:8000]
                })

        return {
            "success": True,
            "text": "Max tool rounds reached. Partial results available.",
            "tool_calls_made": tool_calls_made
        }

    async def _chat(self, messages: list, tools: list,
                    response_format: Optional[dict] = None) -> Optional[dict]:
        """Send a chat request to Ollama's API."""
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": tools if tools else None,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 4096
                }
            }
            if response_format:
                payload["format"] = response_format

            payload = {k: v for k, v in payload.items() if v is not None}

            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        print(f"[Ollama] Error {resp.status}: {text[:200]}")
                        return None
                    return await resp.json()
        except asyncio.TimeoutError:
            print(f"[Ollama] Request timed out ({REQUEST_TIMEOUT}s)")
            return None
        except Exception as e:
            print(f"[Ollama] Request failed: {e}")
            return None

    def _extract_tool_result_text(self, result: dict) -> str:
        """Extract readable text from an MCP tool result."""
        if not result:
            return "No result"

        if result.get("success") and "data" in result:
            data = result["data"]
            if isinstance(data, dict) and "content" in data:
                content_list = data["content"]
                if isinstance(content_list, list):
                    texts = []
                    for item in content_list:
                        if isinstance(item, dict):
                            texts.append(item.get("text", str(item)))
                        else:
                            texts.append(str(item))
                    return "\n".join(texts)
                return str(content_list)
            return json.dumps(data, indent=2) if isinstance(data, dict) else str(data)

        if "error" in result:
            return f"Error: {result['error']}"

        return json.dumps(result, indent=2)


ollama_agent = OllamaAgent()
