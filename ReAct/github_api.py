"""Direct GitHub REST API helpers for repo/PR listing.

We call GitHub directly (not via MCP) for plain data fetching — the MCP server
doesn't expose list-repos tools, and listing is not really agentic work.
The ReAct agent itself still uses MCP tools for the review.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional

import httpx

GITHUB_API = "https://api.github.com"


def _token() -> str:
    return os.getenv("GITHUB_TOKEN", "").strip()


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def list_user_repos(
    *,
    per_page: int = 50,
    visibility: str = "all",
    sort: str = "updated",
) -> List[dict]:
    """List repos the authenticated user has access to (own + collaborator + org)."""
    if not _token():
        raise ValueError("GITHUB_TOKEN is required to list repositories.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{GITHUB_API}/user/repos",
            headers=_headers(),
            params={
                "per_page": per_page,
                "visibility": visibility,
                "sort": sort,
                "affiliation": "owner,collaborator,organization_member",
            },
        )
        response.raise_for_status()
        repos = response.json()

    return [
        {
            "full_name": r["full_name"],
            "owner": r["owner"]["login"],
            "name": r["name"],
            "private": r["private"],
            "default_branch": r.get("default_branch", "main"),
            "description": r.get("description") or "",
            "html_url": r["html_url"],
            "updated_at": r.get("updated_at"),
            "open_issues": r.get("open_issues_count", 0),
        }
        for r in repos
    ]


async def list_repo_prs(
    owner: str,
    repo: str,
    *,
    state: str = "open",
    per_page: int = 50,
) -> List[dict]:
    if not _token():
        raise ValueError("GITHUB_TOKEN is required to list PRs.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            headers=_headers(),
            params={"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"},
        )
        response.raise_for_status()
        prs = response.json()

    return [
        {
            "number": pr["number"],
            "title": pr["title"],
            "author": pr["user"]["login"] if pr.get("user") else "unknown",
            "state": pr["state"],
            "draft": pr.get("draft", False),
            "source_branch": pr["head"]["ref"],
            "destination_branch": pr["base"]["ref"],
            "html_url": pr["html_url"],
            "created_at": pr["created_at"],
            "updated_at": pr["updated_at"],
            "body": (pr.get("body") or "")[:500],
        }
        for pr in prs
    ]


async def get_pr_summary(owner: str, repo: str, pr_id: int | str) -> dict:
    if not _token():
        raise ValueError("GITHUB_TOKEN is required.")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_id}",
            headers=_headers(),
        )
        response.raise_for_status()
        pr = response.json()
    return {
        "number": pr["number"],
        "title": pr["title"],
        "author": pr["user"]["login"] if pr.get("user") else "unknown",
        "state": pr["state"],
        "source_branch": pr["head"]["ref"],
        "destination_branch": pr["base"]["ref"],
        "html_url": pr["html_url"],
        "additions": pr.get("additions", 0),
        "deletions": pr.get("deletions", 0),
        "changed_files": pr.get("changed_files", 0),
        "body": pr.get("body") or "",
    }


async def github_health() -> dict:
    if not _token():
        return {"ok": False, "reason": "GITHUB_TOKEN not set"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{GITHUB_API}/user", headers=_headers())
            if response.status_code != 200:
                return {"ok": False, "status": response.status_code}
            user = response.json()
            return {"ok": True, "login": user.get("login")}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
