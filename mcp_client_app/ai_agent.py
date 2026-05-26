"""
AI Agent using Google Gemini with MCP Tool Calling
"""
import google.generativeai as genai
import json
import os
from typing import Optional, AsyncGenerator
from dotenv import load_dotenv
from mcp_client import mcp_client

load_dotenv()

class GeminiAgent:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or api_key == "your_gemini_api_key_here":
            raise ValueError("Please set GEMINI_API_KEY in .env file")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.chat = None
        self.tools_initialized = False
        
    async def initialize_tools(self):
        """
        Discover tools from MCP server and configure Gemini
        """
        if self.tools_initialized:
            return
            
        print("[Agent] Discovering MCP tools...")
        tools = await mcp_client.discover_tools()
        print(f"[Agent] Found {len(tools)} tools")
        
        if tools:
            # Store tool info for manual function calling
            self.available_tools = {tool["name"]: tool for tool in tools}
        else:
            self.available_tools = {}
            
        self.tools_initialized = True
    
    def _create_system_prompt(self) -> str:
        """
        Create system prompt with available tools
        """
        tools_description = ""
        if self.available_tools:
            tools_description = "\n\nYou have access to the following tools:\n"
            for name, tool in self.available_tools.items():
                desc = tool.get("description", "No description")
                tools_description += f"\n- **{name}**: {desc}"
                
                # Add parameter info
                if "inputSchema" in tool and "properties" in tool["inputSchema"]:
                    props = tool["inputSchema"]["properties"]
                    if props:
                        tools_description += "\n  Parameters:"
                        for param_name, param_info in props.items():
                            param_desc = param_info.get("description", "")
                            param_type = param_info.get("type", "string")
                            tools_description += f"\n    - {param_name} ({param_type}): {param_desc}"
        
        system_prompt = f"""You are an AI assistant that helps users interact with development tools.
You can access GitHub, Bitbucket, JIRA, MEND (security scanning), and other services through MCP tools.

When a user asks you to do something that requires using a tool, respond with a JSON block indicating which tool to call.

Format your tool call like this:
```tool_call
{{
    "tool": "tool_name",
    "arguments": {{
        "param1": "value1",
        "param2": "value2"
    }}
}}
```

After receiving tool results, summarize them clearly for the user.
{tools_description}

Important:
- Always use the exact tool names as listed above
- Provide all required parameters
- If you're unsure which tool to use, ask the user for clarification
- For PR reviews, you'll need the PR number
- For JIRA issues, you'll need the issue key (e.g., PROJ-123)
"""
        return system_prompt
    
    async def process_message(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        Process user message and yield responses (streaming)
        """
        await self.initialize_tools()
        
        # Create chat with system prompt
        system_prompt = self._create_system_prompt()
        
        try:
            # Generate response
            response = self.model.generate_content(
                f"{system_prompt}\n\nUser: {user_message}\n\nAssistant:",
                generation_config=genai.types.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=2048,
                )
            )
            
            response_text = response.text
            
            # Check if response contains a tool call
            if "```tool_call" in response_text:
                # Extract tool call
                start = response_text.find("```tool_call") + len("```tool_call")
                end = response_text.find("```", start)
                tool_call_json = response_text[start:end].strip()
                
                try:
                    tool_call = json.loads(tool_call_json)
                    tool_name = tool_call.get("tool")
                    arguments = tool_call.get("arguments", {})
                    
                    # Yield status update
                    yield f"🔧 Calling tool: **{tool_name}**\n\n"
                    yield f"Parameters: `{json.dumps(arguments)}`\n\n"
                    yield "---\n\n"
                    
                    # Execute the tool
                    result = await mcp_client.call_tool(tool_name, arguments)
                    
                    if result["success"]:
                        tool_result = result["data"]
                        
                        # Format the result
                        yield "**Tool Result:**\n\n"
                        
                        if isinstance(tool_result, dict):
                            # Handle content array from MCP
                            if "content" in tool_result:
                                for content in tool_result["content"]:
                                    if content.get("type") == "text":
                                        yield content.get("text", "") + "\n"
                            else:
                                yield f"```json\n{json.dumps(tool_result, indent=2)}\n```\n"
                        else:
                            yield str(tool_result) + "\n"
                        
                        # Generate summary with Gemini
                        yield "\n---\n\n**Summary:**\n\n"
                        
                        summary_response = self.model.generate_content(
                            f"Summarize this tool result in a clear, helpful way for the user:\n\n{json.dumps(tool_result, indent=2)[:4000]}",
                            generation_config=genai.types.GenerationConfig(
                                temperature=0.5,
                                max_output_tokens=500,
                            )
                        )
                        yield summary_response.text
                        
                    else:
                        yield f"❌ **Error:** {result['error']}\n"
                        
                except json.JSONDecodeError as e:
                    yield f"❌ Failed to parse tool call: {e}\n"
                    yield response_text
            else:
                # No tool call, just return the response
                yield response_text
                
        except Exception as e:
            yield f"❌ **Error:** {str(e)}\n"
    
    async def get_available_tools(self) -> list:
        """
        Get list of available tools
        """
        await self.initialize_tools()
        return list(self.available_tools.keys())


# Singleton instance
agent = GeminiAgent()
