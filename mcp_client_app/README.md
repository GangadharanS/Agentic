# MCP Client Application

A standalone web application that acts as an MCP client host, using Google Gemini AI to interact with MCP tools.

## Architecture

```
┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
│   Web Browser       │      │   MCP Client App    │      │   MCP Server        │
│   (User Interface)  │◄────►│   (Gemini AI)       │◄────►│   (Docker:8000)     │
│   localhost:8080    │      │   localhost:8080    │      │                     │
└─────────────────────┘      └─────────────────────┘      └─────────────────────┘
                                      │                            │
                                      │                            ▼
                                      │                   ┌─────────────────────┐
                                      │                   │   External APIs     │
                                      ▼                   │   GitHub, JIRA,     │
                             ┌─────────────────────┐      │   Bitbucket, MEND   │
                             │   Google Gemini     │      └─────────────────────┘
                             │   (AI Processing)   │
                             └─────────────────────┘
```

## Prerequisites

1. **Python 3.10+** installed
2. **MCP Server** running (Docker container on port 8000)
3. **Google Gemini API Key** (free tier available)

## Getting Your Free Gemini API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the API key

## Installation

### Step 1: Navigate to the application directory

```bash
cd /Users/gasubra/Gangadhar/Gangadhar/Connect/mcp_mend/mcp_client_app
```

### Step 2: Create virtual environment (optional but recommended)

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure environment variables

Edit the `.env` file:

```bash
# Add your Gemini API key
GEMINI_API_KEY=your_actual_gemini_api_key_here

# MCP Server URL (default is localhost:8000)
MCP_SERVER_URL=http://localhost:8000

# Application port
APP_PORT=8080
```

## Running the Application

### Step 1: Ensure MCP Server is running

```bash
# From the mcp_mend directory
cd /Users/gasubra/Gangadhar/Gangadhar/Connect/mcp_mend
docker-compose up -d
```

### Step 2: Start the MCP Client Application

```bash
cd mcp_client_app
python app.py
```

### Step 3: Open in browser

Navigate to: **http://localhost:8080**

## Usage

### Chat Interface

The web interface provides a chat-like experience:

1. Type your request in natural language
2. The Gemini AI will analyze your request
3. If a tool is needed, it will call the MCP server
4. Results are displayed in the chat

### Example Prompts

- "Get information about PR #42 from GitHub"
- "List all open pull requests"
- "Get JIRA issue TCPLT-1234"
- "Analyze MEND project vulnerabilities"
- "Create a new JIRA epic for security fixes"

### Available Tools

The sidebar shows all available MCP tools. Click on any tool to pre-fill a prompt.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface |
| `/api/health` | GET | Check MCP server connection |
| `/api/tools` | GET | List available MCP tools |
| `/api/chat` | POST | Send message to AI (streaming) |
| `/api/tool/call` | POST | Directly call an MCP tool |

### Example API Usage

**List Tools:**
```bash
curl http://localhost:8080/api/tools
```

**Chat:**
```bash
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "List open PRs on GitHub"}'
```

**Direct Tool Call:**
```bash
curl -X POST http://localhost:8080/api/tool/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "get_github_open_prs",
    "arguments": {}
  }'
```

## How It Works

### Communication Flow

1. **User Input**: User types a message in the web interface
2. **AI Processing**: Gemini AI analyzes the message and determines if a tool is needed
3. **Tool Discovery**: The application discovers available tools from the MCP server
4. **Tool Execution**: If needed, the AI generates a tool call which is sent to the MCP server
5. **Response**: Tool results are returned, summarized by AI, and displayed to the user

### MCP Protocol

The application communicates with the MCP server using:
- **SSE (Server-Sent Events)** for tool discovery
- **HTTP POST** to `/messages/` for tool execution
- **JSON-RPC 2.0** message format

## Troubleshooting

### "MCP Server Disconnected"

1. Check if Docker container is running:
   ```bash
   docker ps | grep mcp-server
   ```
2. Restart the MCP server:
   ```bash
   docker-compose restart mcp-server
   ```

### "Please set GEMINI_API_KEY"

1. Ensure `.env` file exists in `mcp_client_app/` directory
2. Add your API key:
   ```
   GEMINI_API_KEY=your_key_here
   ```

### "No tools available"

1. Check MCP server logs:
   ```bash
   docker-compose logs mcp-server
   ```
2. Verify the server is responding:
   ```bash
   curl http://localhost:8000/sse
   ```

## Development

### Project Structure

```
mcp_client_app/
├── app.py              # FastAPI web server
├── mcp_client.py       # MCP client (connects to MCP server)
├── ai_agent.py         # Gemini AI integration
├── requirements.txt    # Python dependencies
├── .env                # Environment variables
├── templates/
│   └── index.html      # Web interface
└── README.md           # This file
```

### Adding Custom Logic

To modify AI behavior, edit `ai_agent.py`:
- `_create_system_prompt()` - Customize AI instructions
- `process_message()` - Modify message processing logic

## License

Internal use only.
