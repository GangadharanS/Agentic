"""High-level GitHub PR review orchestration via ReAct + MCP."""
from __future__ import annotations

from typing import Optional

from mcp_bridge import MCPClient
from prompts import (
    PR_REVIEW_SYSTEM_PROMPT,
    PR_REVIEW_TOOLS,
    PR_REVIEW_USER_TEMPLATE,
)
from react_agent import ReActAgent, parse_json_from_text


class PRReviewAgent:
    def __init__(self, mcp_server_url: Optional[str] = None):
        self.mcp = MCPClient(server_url=mcp_server_url)
        self.agent = ReActAgent(self.mcp)

    async def check_dependencies(self) -> dict:
        mcp_ok = await self.mcp.health_check()
        llm_ok = self.agent.is_available()
        if mcp_ok and not self.mcp.tools:
            await self.mcp.discover_tools()
        return {
            "mcp_server": mcp_ok,
            "gemini": llm_ok,
            "gemini_model": self.agent.model_name,
            "tools_discovered": len(self.mcp.tools),
        }

    async def review(
        self,
        repo: str,
        pr_id: int | str,
        *,
        verbose: bool = True,
        max_rounds: int = 8,
    ) -> dict:
        repo_owner, repo_name = self._parse_repo(repo)
        user_message = PR_REVIEW_USER_TEMPLATE.format(
            pr_id=pr_id,
            repo_owner=repo_owner,
            repo_name=repo_name,
        )

        result = await self.agent.run(
            system_prompt=PR_REVIEW_SYSTEM_PROMPT,
            user_message=user_message,
            tool_filter=PR_REVIEW_TOOLS,
            max_rounds=max_rounds,
            verbose=verbose,
        )

        parsed = parse_json_from_text(result.get("text", ""))
        return {
            "success": result.get("success", False),
            "repo": repo,
            "pr_id": str(pr_id),
            "review": parsed,
            "comments": (parsed or {}).get("comments", []),
            "summary": (parsed or {}).get("summary", {}),
            "raw_response": result.get("text", ""),
            "tool_calls_made": result.get("tool_calls_made", []),
            "react_steps": [
                {
                    "round": s.round_num,
                    "thought": s.thought,
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation": s.observation,
                }
                for s in result.get("steps", [])
            ],
            "error": result.get("error"),
        }

    async def post_review(
        self,
        repo: str,
        pr_id: int | str,
        review: dict,
        *,
        verbose: bool = True,
    ) -> dict:
        repo_owner, repo_name = self._parse_repo(repo)
        comments = review.get("comments") or []

        if not comments:
            review_body = "## ReAct PR Review — Approved\n\nNo logic failures found."
            review_action = "APPROVE"
        else:
            lines = [f"## ReAct PR Review — {len(comments)} issue(s) found\n"]
            for c in comments:
                sev = c.get("severity", "major").upper()
                file_ref = f"`{c.get('file')}` " if c.get("file") else ""
                lines.append(f"- **[{sev}]** {file_ref}{c.get('text', '')}")
            lines.append("\n---\n*Automated review via ReAct + MCP.*")
            review_body = "\n".join(lines)
            review_action = "REQUEST_CHANGES" if any(
                c.get("severity") == "blocking" for c in comments
            ) else "COMMENT"

        # GitHub MCP expects inline comments as a list of
        # {path, line, body, side} objects (no LEFT diff comments by default).
        inline_comments = []
        for c in comments:
            path = c.get("file")
            line = c.get("line")
            body = c.get("text") or ""
            if not path or line is None or not body:
                continue
            inline_comments.append({
                "path": path,
                "line": int(line),
                "body": body,
                "side": "RIGHT",
            })

        # Direct MCP call is reliable for posting; LLM post is optional fallback
        post_result = await self.mcp.call_tool(
            "create_pull_request_review",
            {
                "owner": repo_owner,
                "repo": repo_name,
                "pullNumber": int(pr_id),
                "event": review_action,
                "body": review_body,
                "comments": inline_comments,
            },
        )

        if verbose:
            print(f"\nPosted review: action={review_action}")

        return {
            "success": post_result.get("success", False),
            "review_action": review_action,
            "review_body": review_body,
            "mcp_result": post_result,
        }

    @staticmethod
    def _parse_repo(repo: str) -> tuple[str, str]:
        parts = repo.strip().split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Invalid repo '{repo}'. Use owner/repo-name.")
        return parts[0], parts[1]
