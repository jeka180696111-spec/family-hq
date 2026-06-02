"""GitHub API client for the DevOps agent — branch and PR management."""
from __future__ import annotations

import asyncio
import base64

import httpx
from pydantic import BaseModel
import structlog

log = structlog.get_logger()


class PullRequest(BaseModel):
    number: int
    url: str
    html_url: str
    title: str
    branch: str
    state: str


class GitHubClient:
    """
    GitHub REST API client for the DevOps agent.

    Creates branches and pull requests for code patches.  All requests
    are authenticated with a personal access token and include automatic
    exponential-backoff retries (up to 3 attempts) for transient errors.
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str, repo: str) -> None:
        self._token = token
        self._repo = repo  # "owner/repo"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_branch(
        self, branch_name: str, from_branch: str = "main"
    ) -> bool:
        """
        Create *branch_name* branching off *from_branch*.

        Returns ``True`` on success, ``False`` if the branch already exists.
        """
        # 1. Get the SHA of the source branch tip
        ref_data = await self._request(
            "GET", f"repos/{self._repo}/git/ref/heads/{from_branch}"
        )
        sha: str = ref_data["object"]["sha"]

        # 2. Create the new ref
        try:
            await self._request(
                "POST",
                f"repos/{self._repo}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422:
                log.warning(
                    "github_branch_already_exists",
                    branch=branch_name,
                )
                return False
            raise

        log.info(
            "github_branch_created",
            branch=branch_name,
            from_branch=from_branch,
            sha=sha[:7],
        )
        return True

    async def create_or_update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> bool:
        """
        Create or update a file at *path* on *branch*.

        *content* is plain text; it is base64-encoded before sending.
        Returns ``True`` on success.
        """
        encoded = base64.b64encode(content.encode()).decode()
        endpoint = f"repos/{self._repo}/contents/{path}"

        # Determine if the file already exists so we can supply its SHA
        sha: str | None = None
        try:
            existing = await self._request("GET", endpoint, params={"ref": branch})
            sha = existing.get("sha")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            # File does not exist yet — that is fine, sha stays None

        body: dict = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        await self._request("PUT", endpoint, json=body)
        log.info(
            "github_file_upserted",
            path=path,
            branch=branch,
            updated=sha is not None,
        )
        return True

    async def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> PullRequest:
        """Open a pull request from *head_branch* into *base_branch*."""
        data = await self._request(
            "POST",
            f"repos/{self._repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head_branch,
                "base": base_branch,
            },
        )
        pr = PullRequest(
            number=data["number"],
            url=data["url"],
            html_url=data["html_url"],
            title=data["title"],
            branch=data["head"]["ref"],
            state=data["state"],
        )
        log.info(
            "github_pr_created",
            number=pr.number,
            title=title,
            head=head_branch,
            base=base_branch,
            url=pr.html_url,
        )
        return pr

    async def get_file_content(
        self, path: str, branch: str = "main"
    ) -> str | None:
        """
        Fetch the decoded text content of a file from GitHub.

        Returns ``None`` if the file does not exist.
        """
        try:
            data = await self._request(
                "GET",
                f"repos/{self._repo}/contents/{path}",
                params={"ref": branch},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                log.warning("github_file_not_found", path=path, branch=branch)
                return None
            raise

        encoded: str = data.get("content", "")
        # GitHub wraps base64 in newlines
        text = base64.b64decode(encoded.replace("\n", "")).decode()
        log.debug("github_file_fetched", path=path, branch=branch, size=len(text))
        return text

    async def list_open_prs(self) -> list[PullRequest]:
        """Return all open pull requests in the repository."""
        data = await self._request(
            "GET",
            f"repos/{self._repo}/pulls",
            params={"state": "open", "per_page": 100},
        )
        prs = [
            PullRequest(
                number=pr["number"],
                url=pr["url"],
                html_url=pr["html_url"],
                title=pr["title"],
                branch=pr["head"]["ref"],
                state=pr["state"],
            )
            for pr in data
        ]
        log.debug("github_open_prs_listed", count=len(prs))
        return prs

    async def trigger_redeploy_via_commit(self, branch: str = "main", reason: str = "manual redeploy") -> str:
        """Create an empty commit on `branch` so Railway picks it up and redeploys.

        Returns the new commit SHA.
        """
        from datetime import datetime, timezone

        ref = await self._request("GET", f"repos/{self._repo}/git/ref/heads/{branch}")
        parent_sha = ref["object"]["sha"]

        parent_commit = await self._request("GET", f"repos/{self._repo}/git/commits/{parent_sha}")
        tree_sha = parent_commit["tree"]["sha"]

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        new_commit = await self._request(
            "POST",
            f"repos/{self._repo}/git/commits",
            json={
                "message": f"chore: trigger redeploy ({reason}) — {ts}",
                "tree": tree_sha,
                "parents": [parent_sha],
            },
        )
        new_sha = new_commit["sha"]

        await self._request(
            "PATCH",
            f"repos/{self._repo}/git/refs/heads/{branch}",
            json={"sha": new_sha, "force": False},
        )
        log.info("github_redeploy_commit", sha=new_sha, branch=branch)
        return new_sha

    # ------------------------------------------------------------------
    # Low-level request helper
    # ------------------------------------------------------------------

    async def _request(
        self, method: str, path: str, **kwargs
    ) -> dict | list:
        """Make an authenticated API request with exponential-backoff retry."""
        url = f"{self.BASE_URL}/{path}"
        async with httpx.AsyncClient() as client:
            for attempt in range(3):
                try:
                    resp = await client.request(
                        method,
                        url,
                        headers=self._headers,
                        timeout=30.0,
                        **kwargs,
                    )
                    resp.raise_for_status()
                    # Some endpoints (e.g. DELETE) return 204 with no body
                    if resp.status_code == 204 or not resp.content:
                        return {}
                    return resp.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 422:
                        raise  # Validation errors are not transient
                    if attempt == 2:
                        log.error(
                            "github_request_failed",
                            method=method,
                            path=path,
                            status=exc.response.status_code,
                            error=str(exc),
                        )
                        raise
                    delay = 2**attempt
                    log.warning(
                        "github_request_retry",
                        method=method,
                        path=path,
                        attempt=attempt + 1,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
        # Unreachable, but satisfies type-checker
        raise RuntimeError("Unexpected exit from _request retry loop")
