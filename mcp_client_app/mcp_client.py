"""
MCP Client - Connects to MCP Server and executes tools
Implements proper MCP protocol with initialization handshake.
"""
import aiohttp
import json
import asyncio
from typing import Optional, Any
import os
from dotenv import load_dotenv

load_dotenv()

class MCPClient:
    def __init__(self, server_url: str = None):
        self.server_url = server_url or os.getenv("MCP_SERVER_URL", "http://localhost:8000")
        self.tools: list = []
        self.request_id = 0
        
    def _next_request_id(self) -> str:
        self.request_id += 1
        return f"req-{self.request_id}"
    
    async def discover_tools(self) -> list:
        """
        Discover available tools from MCP server
        """
        try:
            result = await self._mcp_session(method="tools/list", params={})
            if result.get("success") and "data" in result:
                data = result["data"]
                if isinstance(data, dict) and "tools" in data:
                    self.tools = data["tools"]
                    print(f"[MCP] Discovered {len(self.tools)} tools")
                    return self.tools
            return self.tools
        except Exception as e:
            print(f"Error discovering tools: {e}")
            return self.tools
    
    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """
        Call a specific tool on the MCP server
        """
        return await self._mcp_session(
            method="tools/call",
            params={"name": tool_name, "arguments": arguments}
        )
    
    async def _mcp_session(self, method: str, params: dict) -> dict:
        """
        Execute a full MCP session: connect, initialize, call method, return result.
        Each call creates a new session following the MCP protocol.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=120)
            # Increase read buffer size to handle large responses (10MB limit)
            connector = aiohttp.TCPConnector(limit_per_host=10)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector, read_bufsize=10*1024*1024) as session:
                # Connect to SSE endpoint
                async with session.get(f"{self.server_url}/sse") as sse_response:
                    if sse_response.status != 200:
                        return {"success": False, "error": f"SSE connection failed: {sse_response.status}"}
                    
                    messages_endpoint = None
                    initialized = False
                    result_data = None
                    method_request_id = None
                    
                    # Read SSE stream with large buffer for big responses
                    # Use a custom line reader to handle large chunks
                    buffer = b""
                    async for chunk in sse_response.content.iter_any():
                        buffer += chunk
                        # Process all complete lines in the buffer
                        while b"\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\n", 1)
                            line = line_bytes.decode('utf-8').strip()
                            
                            if not line or line.startswith("event:"):
                                continue
                            
                            if not line.startswith("data:"):
                                continue
                                
                            data = line[5:].strip()
                            
                            # Step 1: Get messages endpoint
                            if not messages_endpoint and "messages" in data:
                                messages_endpoint = data.strip('"')
                                messages_url = f"{self.server_url}{messages_endpoint}"
                                print(f"[MCP] Connected: {messages_endpoint}")
                                
                                # Step 2: Send initialize request
                                init_request_id = self._next_request_id()
                                init_request = {
                                    "jsonrpc": "2.0",
                                    "id": init_request_id,
                                    "method": "initialize",
                                    "params": {
                                        "protocolVersion": "2024-11-05",
                                        "capabilities": {
                                            "tools": {}
                                        },
                                        "clientInfo": {
                                            "name": "mcp-client-app",
                                            "version": "1.0.0"
                                        }
                                    }
                                }
                                
                                asyncio.create_task(self._send_post(session, messages_url, init_request))
                                continue
                            
                            # Parse JSON data
                            if data:
                                try:
                                    event_data = json.loads(data)
                                    
                                    # Step 3: Handle initialize response
                                    if not initialized and "result" in event_data:
                                        if "serverInfo" in event_data.get("result", {}) or "capabilities" in event_data.get("result", {}):
                                            initialized = True
                                            print(f"[MCP] Initialized")
                                            
                                            # Send initialized notification
                                            init_notification = {
                                                "jsonrpc": "2.0",
                                                "method": "notifications/initialized"
                                            }
                                            asyncio.create_task(self._send_post(session, messages_url, init_notification))
                                            
                                            # Small delay to ensure notification is processed
                                            await asyncio.sleep(0.1)
                                            
                                            # Step 4: Send the actual method request
                                            method_request_id = self._next_request_id()
                                            method_request = {
                                                "jsonrpc": "2.0",
                                                "id": method_request_id,
                                                "method": method,
                                                "params": params
                                            }
                                            
                                            print(f"[MCP] Calling: {method}")
                                            if "name" in params:
                                                print(f"[MCP] Tool: {params['name']}")
                                            
                                            asyncio.create_task(self._send_post(session, messages_url, method_request))
                                            continue
                                    
                                    # Step 5: Handle method response
                                    if initialized and method_request_id and event_data.get("id") == method_request_id:
                                        print(f"[MCP] Received response")
                                        
                                        if "result" in event_data:
                                            result_data = {"success": True, "data": event_data["result"]}
                                        elif "error" in event_data:
                                            result_data = {"success": False, "error": str(event_data["error"])}
                                        else:
                                            result_data = {"success": True, "data": event_data}
                                        return result_data
                                        
                                except json.JSONDecodeError:
                                    pass
                    
                    if result_data:
                        return result_data
                    else:
                        return {"success": False, "error": "No response received"}
                        
        except asyncio.TimeoutError:
            return {"success": False, "error": "Request timeout"}
        except Exception as e:
            print(f"[MCP] Error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def _send_post(self, session: aiohttp.ClientSession, url: str, body: dict):
        """Send POST request"""
        try:
            async with session.post(url, json=body) as response:
                status = response.status
                if status not in (200, 202):
                    text = await response.text()
                    print(f"[MCP] POST {status}: {text[:100]}")
        except Exception as e:
            print(f"[MCP] POST error: {e}")
    
    def get_tools_for_gemini(self) -> list:
        """
        Convert MCP tools to Gemini function declarations format
        """
        gemini_tools = []
        
        for tool in self.tools:
            parameters = {
                "type": "object",
                "properties": {},
                "required": []
            }
            
            if "inputSchema" in tool:
                schema = tool["inputSchema"]
                if "properties" in schema:
                    parameters["properties"] = schema["properties"]
                if "required" in schema:
                    parameters["required"] = schema["required"]
            
            gemini_tool = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": parameters
            }
            gemini_tools.append(gemini_tool)
        
        return gemini_tools
    
    async def health_check(self) -> bool:
        """
        Check if MCP server is reachable
        """
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.server_url}/sse") as response:
                    return response.status == 200
        except:
            return False


# Singleton instance
mcp_client = MCPClient()
