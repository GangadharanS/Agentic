"""
External MCP Client - Connects to external MCP servers via stdio transport
Supports servers like AWS Documentation MCP Server that use subprocess communication.
"""
import asyncio
import json
import subprocess
import sys
from typing import Optional, Any, Dict, List
import shutil


class StdioMCPClient:
    """MCP Client that communicates via stdio (subprocess) transport"""
    
    def __init__(self, command: str, args: List[str] = None, env: Dict[str, str] = None):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self.tools: List[dict] = []
        self.request_id = 0
        self._initialized = False
        self._read_lock = asyncio.Lock()
        
    def _next_request_id(self) -> str:
        self.request_id += 1
        return f"req-{self.request_id}"
    
    async def start(self) -> bool:
        """Start the MCP server subprocess"""
        try:
            # Check if command exists
            cmd_path = shutil.which(self.command)
            if not cmd_path:
                print(f"[StdioMCP] Command not found: {self.command}")
                return False
            
            # Prepare environment
            import os
            process_env = os.environ.copy()
            process_env.update(self.env)
            
            # Start subprocess
            full_cmd = [cmd_path] + self.args
            print(f"[StdioMCP] Starting: {' '.join(full_cmd)}")
            
            self.process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env
            )
            
            # Wait briefly for process to start
            await asyncio.sleep(0.5)
            
            if self.process.returncode is not None:
                stderr = await self.process.stderr.read()
                print(f"[StdioMCP] Process exited immediately: {stderr.decode()}")
                return False
            
            # Initialize MCP session
            return await self._initialize()
            
        except Exception as e:
            print(f"[StdioMCP] Failed to start: {e}")
            return False
    
    async def _initialize(self) -> bool:
        """Initialize MCP session with handshake"""
        try:
            # Send initialize request
            init_request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "jarvis-agent",
                        "version": "1.0.0"
                    }
                }
            }
            
            response = await self._send_request(init_request)
            if not response or "error" in response:
                print(f"[StdioMCP] Initialize failed: {response}")
                return False
            
            print(f"[StdioMCP] Initialized: {response.get('result', {}).get('serverInfo', {})}")
            
            # Send initialized notification
            await self._send_notification({
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            })
            
            self._initialized = True
            return True
            
        except Exception as e:
            print(f"[StdioMCP] Initialize error: {e}")
            return False
    
    async def _send_request(self, request: dict, timeout: float = 30.0) -> Optional[dict]:
        """Send a JSON-RPC request and wait for response"""
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None
        
        try:
            async with self._read_lock:
                # Send request
                request_json = json.dumps(request) + "\n"
                self.process.stdin.write(request_json.encode())
                await self.process.stdin.drain()
                
                # Read response (with timeout)
                try:
                    line = await asyncio.wait_for(
                        self.process.stdout.readline(),
                        timeout=timeout
                    )
                    if line:
                        return json.loads(line.decode().strip())
                except asyncio.TimeoutError:
                    print(f"[StdioMCP] Request timeout: {request.get('method')}")
                    return None
                    
        except Exception as e:
            print(f"[StdioMCP] Request error: {e}")
            return None
        
        return None
    
    async def _send_notification(self, notification: dict):
        """Send a JSON-RPC notification (no response expected)"""
        if not self.process or not self.process.stdin:
            return
        
        try:
            notification_json = json.dumps(notification) + "\n"
            self.process.stdin.write(notification_json.encode())
            await self.process.stdin.drain()
        except Exception as e:
            print(f"[StdioMCP] Notification error: {e}")
    
    async def discover_tools(self) -> List[dict]:
        """Discover available tools from MCP server"""
        if not self._initialized:
            if not await self.start():
                return []
        
        try:
            request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "tools/list",
                "params": {}
            }
            
            response = await self._send_request(request)
            if response and "result" in response:
                result = response["result"]
                if isinstance(result, dict) and "tools" in result:
                    self.tools = result["tools"]
                    print(f"[StdioMCP] Discovered {len(self.tools)} tools")
                    return self.tools
            
            return []
            
        except Exception as e:
            print(f"[StdioMCP] Discover tools error: {e}")
            return []
    
    async def call_tool(self, tool_name: str, arguments: dict, timeout: float = 60.0) -> dict:
        """Call a tool on the MCP server"""
        if not self._initialized:
            if not await self.start():
                return {"success": False, "error": "Failed to start MCP server"}
        
        try:
            request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            response = await self._send_request(request, timeout=timeout)
            
            if response is None:
                return {"success": False, "error": "No response from MCP server"}
            
            if "error" in response:
                return {"success": False, "error": response["error"]}
            
            if "result" in response:
                return {"success": True, "data": response["result"]}
            
            return {"success": False, "error": "Unknown response format"}
            
        except Exception as e:
            print(f"[StdioMCP] Tool call error: {e}")
            return {"success": False, "error": str(e)}
    
    async def stop(self):
        """Stop the MCP server subprocess"""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except:
                self.process.kill()
            finally:
                self.process = None
                self._initialized = False
    
    def is_running(self) -> bool:
        """Check if the MCP server is running"""
        return self.process is not None and self.process.returncode is None


class ExternalMCPManager:
    """Manages multiple external MCP server connections"""
    
    def __init__(self):
        self.clients: Dict[str, StdioMCPClient] = {}
        self._configs = {
            "aws-docs": {
                "command": "uvx",
                "args": ["awslabs.aws-documentation-mcp-server@latest"],
                "env": {
                    "FASTMCP_LOG_LEVEL": "ERROR",
                    "AWS_DOCUMENTATION_PARTITION": "aws"
                }
            },
            "aws-diagram": {
                "command": "uvx",
                "args": ["awslabs.aws-diagram-mcp-server"],
                "env": {
                    "FASTMCP_LOG_LEVEL": "ERROR"
                }
            },
            "awslabs.aws-diagram-mcp-server": {
                "command": "uvx",
                "args": ["awslabs.aws-diagram-mcp-server"],
                "env": {
                    "FASTMCP_LOG_LEVEL": "ERROR"
                }
            }
        }
    
    async def get_client(self, server_id: str) -> Optional[StdioMCPClient]:
        """Get or create a client for the specified server"""
        if server_id in self.clients:
            client = self.clients[server_id]
            if client.is_running():
                return client
        
        # Create new client
        if server_id not in self._configs:
            print(f"[ExternalMCP] Unknown server: {server_id}")
            return None
        
        config = self._configs[server_id]
        client = StdioMCPClient(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env", {})
        )
        
        if await client.start():
            self.clients[server_id] = client
            return client
        
        return None
    
    async def discover_tools(self, server_id: str) -> List[dict]:
        """Discover tools for a specific server"""
        client = await self.get_client(server_id)
        if client:
            return await client.discover_tools()
        return []
    
    async def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> dict:
        """Call a tool on a specific server"""
        client = await self.get_client(server_id)
        if client:
            return await client.call_tool(tool_name, arguments)
        return {"success": False, "error": f"Could not connect to server: {server_id}"}
    
    async def stop_all(self):
        """Stop all running clients"""
        for client in self.clients.values():
            await client.stop()
        self.clients.clear()
    
    def add_server_config(self, server_id: str, command: str, args: List[str] = None, env: Dict[str, str] = None):
        """Add or update a server configuration"""
        self._configs[server_id] = {
            "command": command,
            "args": args or [],
            "env": env or {}
        }


# Global instance
external_mcp_manager = ExternalMCPManager()
