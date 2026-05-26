"""
Jarvis Agent v4.0 - LLM-Only Tool Calling
All MCP tool selection is delegated to the Ollama LLM (Llama 3).
No pattern matching, no hardcoded tool calls, no regex parsing.
Ollama is REQUIRED -- the app will not start without it.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import os
import json
from dotenv import load_dotenv

load_dotenv()

from mcp_client import mcp_client
from external_mcp_client import external_mcp_manager
from ollama_agent import ollama_agent
from atlassian import Jira

# ---------------------------------------------------------------------------
# JIRA client
# ---------------------------------------------------------------------------

def get_jira_client():
    jira_url = os.getenv('JIRA_BASE_URL', 'https://jira.trimble.tools')
    jira_token = os.getenv('JIRA_API_TOKEN', '')
    if not jira_token:
        print("[JIRA] Missing API token")
        return None
    return Jira(url=jira_url, token=jira_token, cloud=False)


# ---------------------------------------------------------------------------
# LLM System Prompts -- one per endpoint domain
# ---------------------------------------------------------------------------

LLM_PR_LIST_PROMPT = """You are a GitHub assistant with access to MCP tools.

Use the get_open_prs_for_repo tool to list pull requests.

Return ONLY a JSON object with this exact structure:
{
  "prs": [
    {"number": "123", "title": "PR title", "author": "username", "branch": "feature/x"}
  ]
}"""

LLM_PR_SEARCH_PROMPT = """You are a GitHub assistant with access to MCP tools.

Use get_pr_information_universal to find information about a specific pull request.

Return ONLY a JSON object with this structure:
{
  "number": "123",
  "title": "PR title",
  "author": "username",
  "repo": "owner/repo",
  "branch": "feature/x",
  "status": "Open",
  "description": "brief description"
}"""

LLM_PR_REVIEW_PROMPT = """You are an expert code reviewer with access to MCP tools for GitHub.

When asked to review a PR:
1. Use get_pr_information_universal to get PR metadata
2. Use get_pr_files to get the changed files with content
3. Use analyze_pr_logic_changes to get analysis

Analyze the changes and identify ONLY logic failures:
- Business logic errors
- Null safety issues, off-by-one errors, race conditions
- Security vulnerabilities
- Breaking changes to existing functionality

Do NOT flag style, formatting, or documentation issues.

Return ONLY a JSON object with this exact structure:
{
  "comments": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "text": "Description of the logic failure",
      "type": "logic_error",
      "category": "Null Safety",
      "severity": "blocking"
    }
  ],
  "summary": {
    "source_branch": "feature/x",
    "destination_branch": "main",
    "files_analyzed": 3,
    "files": ["file1.py", "file2.py"],
    "pr_title": "Title of the PR"
  }
}

Severity levels: blocking (must fix), major (should fix), minor (consider fixing).
If no issues found, return empty comments array."""

LLM_PR_APPLY_COMMENTS_PROMPT = """You are a GitHub assistant with access to MCP tools.

Use the create_github_pr_review tool to post review comments on a pull request.
You will be given the PR number, repository, and the review body to post.

After posting, return a JSON object:
{
  "success": true,
  "message": "Review posted successfully",
  "review_url": "URL if available"
}"""

LLM_PR_APPLY_FIXES_PROMPT = """You are a GitHub assistant with access to MCP tools.

Use the auto_fix_review_issues tool to apply fixes to a pull request.
You will be given the PR number, repository, and the issues to fix.

Return a JSON object:
{
  "success": true,
  "message": "Applied N fixes to PR #X"
}"""

LLM_DOCS_PROMPT = """You are a technical documentation expert with access to MCP tools for GitHub.

When asked to generate documentation:
1. Use get_github_repo_tree to understand the repository structure
2. Use get_github_file_content to read key files (README, config files, entry points)
3. Analyze the codebase and generate comprehensive documentation

Generate well-structured markdown documentation covering:
- Project overview and purpose
- Architecture and key components
- Setup and installation instructions
- API endpoints (if applicable)
- Configuration options
- Dependencies"""

LLM_ASSISTANT_PROMPT = """You are Jarvis, an AI assistant for software development teams.

You have access to MCP tools for:
- GitHub: PRs, code browsing, branches, commits
- JIRA: Issue tracking, bug reports
- Mend: Security vulnerability scanning

Help the user with their query by using the appropriate tools. Be concise and helpful.
When referencing PRs, use the format "PR #123".
When referencing JIRA tickets, use the format "PROJ-123".
Always explain what you found and provide actionable insights."""

LLM_BRANCHES_PROMPT = """You are a GitHub assistant with access to MCP tools.

Use the list_github_branches tool to list branches for a repository.

Return ONLY a JSON object:
{
  "branches": ["main", "develop", "feature/x"]
}"""

LLM_BUG_ANALYZE_PROMPT = """You are an expert software engineer analyzing bug reports.
You have access to MCP tools for GitHub to browse repository code.

When analyzing a bug:
1. Read the bug description carefully
2. Use get_github_repo_tree to understand the repository structure
3. Use get_github_file_content to read potentially affected files
4. Identify the root cause based on the bug description and code

Return ONLY a JSON object:
{
  "root_cause": "Clear explanation of what causes the bug",
  "affected_files": ["path/to/file1.py", "path/to/file2.py"],
  "proposed_fix": "Detailed description of how to fix the bug",
  "confidence": "high|medium|low",
  "severity_assessment": "Brief assessment of impact"
}"""

LLM_BUG_FIX_PROMPT = """You are a GitHub assistant with access to MCP tools.

To apply a bug fix:
1. Use create_github_branch to create a new branch from the base branch
2. Use commit_files_to_github to commit the fix files to the new branch

Return a JSON object:
{
  "success": true,
  "branch_name": "fix/BUG-123",
  "files_modified": 1,
  "message": "Branch created and fix committed"
}"""

LLM_BUG_PR_PROMPT = """You are a GitHub assistant with access to MCP tools.

Use create_github_pull_request to create a pull request for a bug fix.

Return a JSON object:
{
  "success": true,
  "pr_url": "https://github.com/...",
  "pr_number": "456",
  "message": "PR created successfully"
}"""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class OpenPRsRequest(BaseModel):
    repo: str

class PRListRequest(BaseModel):
    repo: str
    status: str = "open"

class PRSearchRequest(BaseModel):
    query: str
    search_type: str = "number"
    repo: str

class PRReviewRequest(BaseModel):
    pr_id: str
    repo: str

class ReviewIssue(BaseModel):
    file: Optional[str] = None
    text: str
    type: Optional[str] = "suggestion"
    line: Optional[int] = None
    category: Optional[str] = None
    severity: Optional[str] = "minor"

class ApplyFixesRequest(BaseModel):
    pr_id: str
    repo: str
    issues: List[ReviewIssue]

class ReviewSummary(BaseModel):
    pr_title: Optional[str] = None
    source_branch: Optional[str] = None
    destination_branch: Optional[str] = None
    files_analyzed: Optional[int] = 0
    files: Optional[List[str]] = []
    file_changes: Optional[List[dict]] = []
    checks_performed: Optional[List[str]] = []

class ApplyCommentsRequest(BaseModel):
    pr_id: str
    repo: str
    comments: List[ReviewIssue]
    action: str = "COMMENT"
    is_approval: bool = False
    is_documentation_pr: bool = False
    review_summary: Optional[ReviewSummary] = None

class AssistantQueryRequest(BaseModel):
    prompt: str
    server_id: Optional[str] = "default"
    server_url: Optional[str] = "http://localhost:8000"

class DocumentationRequest(BaseModel):
    server_id: str
    repository: str
    doc_type: str = "readme"
    format: str = "markdown"
    include_aws_docs: bool = True
    analyze_code_logic: bool = True

class DiagramDocRequest(BaseModel):
    server_id: str
    repository: str
    doc_type: str = "aws_architecture"
    format: str = "markdown"

class BugAnalyzeRequest(BaseModel):
    bug_key: str
    repo: str

class BugApplyFixRequest(BaseModel):
    bug_key: str
    repo: str
    base_branch: str = "main"
    analysis: Optional[dict] = None

class BugRaisePRRequest(BaseModel):
    bug_key: str
    repo: str
    branch_name: str
    base_branch: str

class ExternalMCPConnectRequest(BaseModel):
    server_id: str
    server_url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[dict] = None

class ExternalMCPToolCallRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict = {}


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Jarvis Agent", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """Initialize MCP tools and require Ollama at startup."""
    print("[Startup] Discovering MCP tools...")
    tools = await mcp_client.discover_tools()
    print(f"[Startup] Found {len(tools)} MCP tools")
    await ollama_agent.require_available()
    print(f"[Startup] Ollama OK (model: {ollama_agent.model})")


# ---------------------------------------------------------------------------
# Helper: parse LLM JSON response
# ---------------------------------------------------------------------------

def _parse_llm_json(text: str) -> Optional[dict]:
    """Extract and parse JSON from LLM response text."""
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Infrastructure endpoints (unchanged)
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health_check():
    mcp_healthy = await mcp_client.health_check()
    ollama_ok = await ollama_agent.is_available()
    return {
        "status": "ok",
        "mcp_server": {"url": mcp_client.server_url, "connected": mcp_healthy},
        "llm": {
            "provider": "ollama",
            "model": ollama_agent.model,
            "available": ollama_ok,
            "url": ollama_agent.base_url,
        },
    }


@app.get("/api/repos")
async def list_repositories():
    return {
        "repos": [
            {"full_name": "Trimble-Connect/trimble-connect-platform", "name": "trimble-connect-platform"},
            {"full_name": "Trimble-Connect/cloud-files-service-utils", "name": "cloud-files-service-utils"},
            {"full_name": "Trimble-Connect/trimble-connect-permissions-service", "name": "trimble-connect-permissions-service"},
            {"full_name": "Trimble-Connect/trimble-connect-files-service", "name": "trimble-connect-files-service"},
            {"full_name": "Trimble-Connect/tc-api-gateway", "name": "tc-api-gateway"},
            {"full_name": "Trimble-Connect/tc-auth-service", "name": "tc-auth-service"},
            {"full_name": "Trimble-Connect/tc-project-service", "name": "tc-project-service"},
        ]
    }


@app.get("/api/tools")
async def list_tools():
    try:
        tools = await mcp_client.discover_tools()
        return {
            "count": len(tools),
            "tools": [
                {"name": t["name"], "description": t.get("description", "")}
                for t in tools
            ],
        }
    except Exception as e:
        return {"error": str(e), "tools": []}


# ---------------------------------------------------------------------------
# External MCP endpoints (unchanged)
# ---------------------------------------------------------------------------

@app.post("/api/external-mcp/connect")
async def connect_external_mcp(request: ExternalMCPConnectRequest):
    try:
        if request.command:
            external_mcp_manager.add_server_config(
                request.server_id, request.command, request.args, request.env
            )
        client = await external_mcp_manager.get_client(request.server_id)
        if client and client.is_running():
            tools = await client.discover_tools()
            return {
                "success": True,
                "server_id": request.server_id,
                "connected": True,
                "tools": [{"name": t.get("name", ""), "description": t.get("description", "")} for t in tools],
            }
        return {"success": False, "server_id": request.server_id, "connected": False, "error": "Failed to start MCP server"}
    except Exception as e:
        return {"success": False, "server_id": request.server_id, "error": str(e)}


@app.get("/api/external-mcp/{server_id}/tools")
async def list_external_mcp_tools(server_id: str):
    try:
        tools = await external_mcp_manager.discover_tools(server_id)
        return {
            "server_id": server_id,
            "count": len(tools),
            "tools": [{"name": t.get("name", ""), "description": t.get("description", "")} for t in tools],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/external-mcp/call")
async def call_external_mcp_tool(request: ExternalMCPToolCallRequest):
    try:
        return await external_mcp_manager.call_tool(request.server_id, request.tool_name, request.arguments)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# PR endpoints -- ALL delegated to Ollama LLM
# ---------------------------------------------------------------------------

@app.post("/api/pr/open-prs")
async def get_open_prs(request: OpenPRsRequest):
    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}
    result = await ollama_agent.run(
        system_prompt=LLM_PR_LIST_PROMPT,
        user_message=f"List all open pull requests for repository {request.repo}.",
        tool_filter=["get_open_prs_for_repo", "get_github_open_pr_list"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed"), "prs": []}
    parsed = _parse_llm_json(result["text"])
    if parsed and "prs" in parsed:
        return {"prs": parsed["prs"], "repo": request.repo}
    return {"prs": [], "repo": request.repo, "raw_response": result["text"]}


@app.post("/api/pr/list")
async def list_prs_by_status(request: PRListRequest):
    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}
    result = await ollama_agent.run(
        system_prompt=LLM_PR_LIST_PROMPT,
        user_message=(
            f"List pull requests with status '{request.status}' "
            f"for repository {request.repo}."
        ),
        tool_filter=["get_open_prs_for_repo"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed"), "prs": []}
    parsed = _parse_llm_json(result["text"])
    if parsed and "prs" in parsed:
        return {"prs": parsed["prs"], "repo": request.repo, "status": request.status}
    return {"prs": [], "repo": request.repo, "status": request.status, "raw_response": result["text"]}


@app.post("/api/pr/search")
async def search_pr(request: PRSearchRequest):
    result = await ollama_agent.run(
        system_prompt=LLM_PR_SEARCH_PROMPT,
        user_message=(
            f"Find PR #{request.query} in repository {request.repo}. "
            f"Search type: {request.search_type}."
        ),
        tool_filter=["get_pr_information_universal", "get_pr_files"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed")}
    parsed = _parse_llm_json(result["text"])
    if parsed:
        parsed.setdefault("repo", request.repo)
        return parsed
    return {"number": request.query, "repo": request.repo, "raw_response": result["text"]}


@app.post("/api/pr/review")
async def review_pr(request: PRReviewRequest):
    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}
    repo_owner, repo_name = repo_parts

    result = await ollama_agent.run(
        system_prompt=LLM_PR_REVIEW_PROMPT,
        user_message=(
            f"Review PR #{request.pr_id} in repository {repo_owner}/{repo_name}. "
            f"Use the available tools to get PR info, fetch changed files, "
            f"and analyze logic changes. Report any logic failures found."
        ),
        tool_filter=[
            "get_pr_information_universal", "get_pr_files",
            "analyze_pr_logic_changes", "get_pr_file_paths",
            "get_github_file_content",
        ],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed"), "comments": []}
    parsed = _parse_llm_json(result["text"])
    if parsed and "comments" in parsed:
        parsed["pr_id"] = request.pr_id
        parsed["repo"] = request.repo
        parsed["analysis_method"] = "llm"
        return parsed
    return {
        "comments": [],
        "pr_id": request.pr_id,
        "repo": request.repo,
        "analysis_method": "llm",
        "raw_response": result["text"],
    }


@app.post("/api/pr/apply-comments")
async def apply_comments(request: ApplyCommentsRequest):
    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}
    repo_owner, repo_name = repo_parts

    if request.is_approval or request.action == "APPROVE" or len(request.comments) == 0:
        review_body = "## JarvisAgent Review - Approved\n\nNo logic failures found. Good for approval."
    else:
        lines = [f"## JarvisAgent Review - Issues Found ({len(request.comments)})\n"]
        for c in request.comments:
            sev = {"blocking": "BLOCKING", "major": "MAJOR", "minor": "MINOR"}.get(c.severity, "INFO")
            file_ref = f"`{c.file}` " if c.file else ""
            lines.append(f"- **[{sev}]** {file_ref}{c.text}")
        lines.append("\n---\n*Automated review by JarvisAgent.*")
        review_body = "\n".join(lines)

    result = await ollama_agent.run(
        system_prompt=LLM_PR_APPLY_COMMENTS_PROMPT,
        user_message=(
            f"Post a review comment on PR #{request.pr_id} in repository "
            f"{repo_owner}/{repo_name}. "
            f"Use review_action='COMMENT'. "
            f"The review body is:\n\n{review_body}"
        ),
        tool_filter=["create_github_pr_review", "create_and_submit_github_pr_review"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed"), "success": False}
    parsed = _parse_llm_json(result["text"])
    if parsed:
        return parsed
    return {"success": True, "message": f"Review posted to PR #{request.pr_id}", "raw_response": result["text"]}


@app.post("/api/pr/apply-fixes")
async def apply_fixes(request: ApplyFixesRequest):
    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}
    repo_owner, repo_name = repo_parts

    issues_list = [
        {"file": issue.file or "general", "text": issue.text, "type": issue.type or "suggestion"}
        for issue in request.issues
    ]
    result = await ollama_agent.run(
        system_prompt=LLM_PR_APPLY_FIXES_PROMPT,
        user_message=(
            f"Apply fixes to PR #{request.pr_id} in repository {repo_owner}/{repo_name}. "
            f"Issues to fix:\n{json.dumps(issues_list, indent=2)}"
        ),
        tool_filter=["auto_fix_review_issues"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed")}
    parsed = _parse_llm_json(result["text"])
    if parsed:
        return parsed
    return {"success": True, "message": f"Applied {len(request.issues)} fixes", "raw_response": result["text"]}


# ---------------------------------------------------------------------------
# Documentation endpoints -- delegated to Ollama LLM
# ---------------------------------------------------------------------------

@app.post("/api/docs/generate")
async def generate_documentation(request: DocumentationRequest):
    repo_parts = request.repository.replace("https://github.com/", "").replace("github.com/", "").split("/")
    repo_owner = repo_parts[0] if len(repo_parts) > 0 else ""
    repo_name = repo_parts[1] if len(repo_parts) > 1 else request.repository

    result = await ollama_agent.run(
        system_prompt=LLM_DOCS_PROMPT,
        user_message=(
            f"Generate {request.doc_type} documentation for the repository "
            f"{repo_owner}/{repo_name}. "
            f"Use the available GitHub tools to browse the repository structure "
            f"and read key files. Generate comprehensive markdown documentation."
        ),
        tool_filter=[
            "get_github_repo_tree", "get_github_file_content",
            "get_pr_file_paths",
        ],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed")}
    return {
        "documentation": result["text"],
        "repository": request.repository,
        "type": request.doc_type,
        "format": request.format,
        "server_id": request.server_id,
        "analysis_method": "llm",
    }


@app.post("/api/docs/generate-with-diagram")
async def generate_documentation_with_diagram(request: DiagramDocRequest):
    repo_parts = request.repository.replace("https://github.com/", "").replace("github.com/", "").split("/")
    repo_owner = repo_parts[0] if len(repo_parts) > 0 else ""
    repo_name = repo_parts[1] if len(repo_parts) > 1 else request.repository

    result = await ollama_agent.run(
        system_prompt=LLM_DOCS_PROMPT + "\n\nInclude architecture diagrams using mermaid syntax where appropriate.",
        user_message=(
            f"Generate {request.doc_type} documentation with diagrams for the repository "
            f"{repo_owner}/{repo_name}."
        ),
        tool_filter=["get_github_repo_tree", "get_github_file_content"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed")}
    return {
        "documentation": result["text"],
        "repository": request.repository,
        "type": request.doc_type,
        "format": request.format,
        "server_id": request.server_id,
        "analysis_method": "llm",
    }


# ---------------------------------------------------------------------------
# Assistant / Chat endpoint -- delegated to Ollama LLM
# ---------------------------------------------------------------------------

@app.post("/api/assistant/query")
async def assistant_query(request: AssistantQueryRequest):
    result = await ollama_agent.run(
        system_prompt=LLM_ASSISTANT_PROMPT,
        user_message=request.prompt,
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed")}
    return {
        "response": result["text"],
        "server": "Ollama + MCP Tools",
        "tools_used": [tc["tool"] for tc in result.get("tool_calls_made", [])],
    }


# ---------------------------------------------------------------------------
# Branches endpoint -- delegated to Ollama LLM
# ---------------------------------------------------------------------------

@app.get("/api/branches")
async def get_branches(repo: str):
    repo_parts = repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format", "branches": []}

    result = await ollama_agent.run(
        system_prompt=LLM_BRANCHES_PROMPT,
        user_message=f"List all branches for repository {repo}.",
        tool_filter=["list_github_branches"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed"), "branches": []}
    parsed = _parse_llm_json(result["text"])
    if parsed and "branches" in parsed:
        return {"branches": parsed["branches"], "repo": repo}
    return {"branches": [], "repo": repo, "raw_response": result["text"]}


# ---------------------------------------------------------------------------
# Jenkins / Allure endpoints -- call MCP tools via mcp_client
# ---------------------------------------------------------------------------

@app.get("/api/jenkins/last-build")
async def jenkins_last_build(job_path: str = None):
    """Get last Jenkins build info via MCP tool."""
    try:
        args = {}
        if job_path:
            args["job_path"] = job_path
        result = await mcp_client.call_tool("get_jenkins_last_build", args)
        content = extract_content_from_result(result)
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"raw": content}
        return {"error": "No result from Jenkins"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/jenkins/allure-report")
async def jenkins_allure_report(build_number: str = "lastBuild", job_path: str = None):
    """Get Allure test report summary via MCP tool."""
    try:
        args = {"build_number": build_number}
        if job_path:
            args["job_path"] = job_path
        result = await mcp_client.call_tool("get_jenkins_allure_report", args)
        content = extract_content_from_result(result)
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"raw": content}
        return {"error": "No result from Jenkins"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/jenkins/allure-failures")
async def jenkins_allure_failures(build_number: str = "lastBuild", job_path: str = None):
    """Get failed test details from Allure report via MCP tool."""
    try:
        args = {"build_number": build_number}
        if job_path:
            args["job_path"] = job_path
        result = await mcp_client.call_tool("get_jenkins_allure_failures", args)
        content = extract_content_from_result(result)
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"raw": content}
        return {"error": "No result from Jenkins"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/jenkins/build-history")
async def jenkins_build_history(count: int = 10, job_path: str = None):
    """Get Jenkins build history via MCP tool."""
    try:
        args = {"count": count}
        if job_path:
            args["job_path"] = job_path
        result = await mcp_client.call_tool("get_jenkins_build_history", args)
        content = extract_content_from_result(result)
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"raw": content}
        return {"error": "No result from Jenkins"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Bug endpoints -- JIRA open bugs stays direct; rest delegated to Ollama LLM
# ---------------------------------------------------------------------------

@app.get("/api/bugs/open")
async def get_open_bugs():
    """Get open bug tickets from JIRA (direct JIRA API, no MCP)."""
    try:
        jira_client = get_jira_client()
        if jira_client is None:
            return {"error": "JIRA client not configured", "bugs": []}

        jql = "project = TCJARVIS AND status not in (Done, Closed, Resolved) ORDER BY priority DESC, created DESC"
        result = jira_client.jql(jql, limit=50)
        bugs = []
        if result and "issues" in result:
            for issue in result["issues"]:
                fields = issue.get("fields", {})
                bugs.append({
                    "key": issue.get("key"),
                    "summary": fields.get("summary"),
                    "description": fields.get("description", "") or "",
                    "priority": fields.get("priority", {}).get("name", "Medium") if fields.get("priority") else "Medium",
                    "status": fields.get("status", {}).get("name", "Open") if fields.get("status") else "Open",
                    "issuetype": fields.get("issuetype", {}).get("name", "Task") if fields.get("issuetype") else "Task",
                    "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None,
                    "reporter": fields.get("reporter", {}).get("displayName") if fields.get("reporter") else None,
                    "created": fields.get("created"),
                })
        return {"bugs": bugs, "total": len(bugs)}
    except Exception as e:
        return {"error": str(e), "bugs": []}


@app.post("/api/bugs/analyze")
async def analyze_bug(request: BugAnalyzeRequest):
    jira_client = get_jira_client()
    if jira_client is None:
        return {"error": "JIRA client not configured"}

    issue = jira_client.issue(request.bug_key)
    if not issue:
        return {"error": f"Could not fetch JIRA issue {request.bug_key}"}

    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    description = fields.get("description", "") or ""
    priority = fields.get("priority", {}).get("name", "Unknown")

    comments_data = fields.get("comment", {}).get("comments", [])
    comment_texts = []
    for c in comments_data[-5:]:
        body = c.get("body", "")
        author = c.get("author", {}).get("displayName", "")
        if body:
            comment_texts.append(f"{author}: {body[:200]}")

    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}

    result = await ollama_agent.run(
        system_prompt=LLM_BUG_ANALYZE_PROMPT,
        user_message=(
            f"Analyze this bug from JIRA:\n\n"
            f"Key: {request.bug_key}\n"
            f"Summary: {summary}\n"
            f"Priority: {priority}\n"
            f"Description: {description[:1500]}\n"
            f"Recent Comments: {'; '.join(comment_texts[:3])}\n\n"
            f"Repository: {request.repo}\n\n"
            f"Find the root cause, identify affected files in the repo, and propose a fix."
        ),
        tool_filter=[
            "get_github_repo_tree", "get_github_file_content",
            "get_pr_file_paths",
        ],
    )

    analysis = {
        "bug_key": request.bug_key,
        "summary": summary,
        "status": fields.get("status", {}).get("name", "Unknown"),
        "priority": priority,
        "type": fields.get("issuetype", {}).get("name", "Bug"),
        "assignee": fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned",
        "reporter": fields.get("reporter", {}).get("displayName", "Unknown") if fields.get("reporter") else "Unknown",
        "created": fields.get("created", ""),
        "labels": fields.get("labels", []),
        "components": [c.get("name", "") for c in fields.get("components", [])],
        "root_cause": "",
        "affected_files": [],
        "proposed_fix": "",
        "confidence": "medium",
        "analysis_method": "llm",
    }

    if result.get("success") and result.get("text"):
        parsed = _parse_llm_json(result["text"])
        if parsed:
            analysis["root_cause"] = parsed.get("root_cause", "")
            analysis["affected_files"] = parsed.get("affected_files", [])
            analysis["proposed_fix"] = parsed.get("proposed_fix", "")
            analysis["confidence"] = parsed.get("confidence", "medium")
            if parsed.get("severity_assessment"):
                analysis["severity_assessment"] = parsed["severity_assessment"]
    else:
        analysis["error"] = result.get("error", "LLM analysis failed")

    if comment_texts:
        analysis["recent_comments"] = comment_texts
    return analysis


@app.post("/api/bugs/apply-fix")
async def apply_bug_fix(request: BugApplyFixRequest):
    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}
    repo_owner, repo_name = repo_parts
    branch_name = f"fix/{request.bug_key.lower()}"
    base_branch = request.base_branch or "main"

    jira_client = get_jira_client()
    bug_summary = request.bug_key
    description = ""
    if jira_client:
        try:
            issue = jira_client.issue(request.bug_key)
            if issue:
                fields = issue.get("fields", {})
                bug_summary = fields.get("summary", request.bug_key)
                description = fields.get("description", "") or ""
        except Exception:
            pass

    analysis = request.analysis or {}
    proposed_fix = analysis.get("proposed_fix", "")
    root_cause = analysis.get("root_cause", description)

    result = await ollama_agent.run(
        system_prompt=LLM_BUG_FIX_PROMPT,
        user_message=(
            f"Apply a bug fix for {request.bug_key} in repository {repo_owner}/{repo_name}.\n\n"
            f"1. Create branch '{branch_name}' from '{base_branch}'\n"
            f"2. Commit a fix summary file at docs/fixes/{request.bug_key.upper()}-fix-summary.md "
            f"with this content:\n\n"
            f"## Fix for {request.bug_key}: {bug_summary}\n\n"
            f"### Root Cause\n{root_cause[:500]}\n\n"
            f"### Proposed Fix\n{proposed_fix or 'Manual investigation required.'}\n\n"
            f"Use commit message: fix({request.bug_key}): {bug_summary[:80]}"
        ),
        tool_filter=["create_github_branch", "commit_files_to_github"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed")}
    parsed = _parse_llm_json(result["text"])
    base_response = {
        "success": True,
        "bug_key": request.bug_key,
        "branch_name": branch_name,
        "base_branch": base_branch,
        "summary": bug_summary,
        "message": f"Branch '{branch_name}' created and fix committed for {request.bug_key}",
    }
    if parsed:
        base_response.update(parsed)
    return base_response


@app.post("/api/bugs/raise-pr")
async def raise_bug_pr(request: BugRaisePRRequest):
    repo_parts = request.repo.split("/")
    if len(repo_parts) != 2:
        return {"error": "Invalid repo format. Use 'owner/repo-name'"}
    repo_owner, repo_name = repo_parts

    jira_client = get_jira_client()
    bug_summary = request.bug_key
    if jira_client:
        try:
            issue = jira_client.issue(request.bug_key)
            if issue:
                bug_summary = issue.get("fields", {}).get("summary", request.bug_key)
        except Exception:
            pass

    pr_title = f"Fix: {request.bug_key} - {bug_summary[:80]}"
    pr_body = (
        f"## Bug Fix for {request.bug_key}\n\n"
        f"**Bug:** {bug_summary}\n\n"
        f"**Branch:** `{request.branch_name}` (from `{request.base_branch}`)\n\n"
        f"---\n*Created by JarvisAgent.*"
    )

    result = await ollama_agent.run(
        system_prompt=LLM_BUG_PR_PROMPT,
        user_message=(
            f"Create a pull request in repository {repo_owner}/{repo_name}.\n"
            f"Title: {pr_title}\n"
            f"Body: {pr_body}\n"
            f"Head branch: {request.branch_name}\n"
            f"Base branch: {request.base_branch}"
        ),
        tool_filter=["create_github_pull_request"],
    )
    if not result.get("success"):
        return {"error": result.get("error", "LLM request failed")}
    parsed = _parse_llm_json(result["text"])
    base_response = {
        "success": True,
        "bug_key": request.bug_key,
        "branch_name": request.branch_name,
        "base_branch": request.base_branch,
        "message": f"PR raised for {request.bug_key}",
    }
    if parsed:
        base_response.update(parsed)
    return base_response


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", 8080))
    print(f"""
====================================================
  Jarvis Agent v4.0 (LLM-Only Tool Calling)
====================================================
  Web Interface: http://localhost:{port}
  MCP Server:    {mcp_client.server_url}
  LLM:           Ollama ({ollama_agent.model})
  Mode:          ALL tool calls via LLM (no fallback)
====================================================
    """)
    uvicorn.run(app, host="0.0.0.0", port=port)
