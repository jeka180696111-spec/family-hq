from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger()

class DevOpsAgent(BaseAgent):
    """
    Прораб — monitors system health, creates GitHub PRs for fixes,
    manages agent hiring/firing workflow.
    """

    agent_id = "devops"
    emoji = "🛠️"
    name = "Прораб"

    def __init__(self, *args, github_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._github = github_client

    def get_system_prompt(self) -> str:
        from src.prompts.devops import get_devops_prompt
        return get_devops_prompt(active_agents=[])

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "read_logs",
                "description": "Прочитать логи системы",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["INFO", "WARNING", "ERROR", "CRITICAL"], "default": "ERROR"},
                        "agent_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            },
            {
                "name": "create_github_pr",
                "description": "Создать Pull Request в GitHub",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "branch": {"type": "string"},
                        "body": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                            },
                        },
                    },
                    "required": ["title", "branch", "body"],
                },
            },
            {
                "name": "ping_external",
                "description": "Проверить внешний сервис",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "enum": ["matveika_bot", "finance_bot", "anthropic_api"]},
                    },
                    "required": ["service"],
                },
            },
            {
                "name": "read_file",
                "description": "Прочитать файл проекта",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Путь относительно корня проекта"},
                    },
                    "required": ["path"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "read_logs":
            async with self._memory._engine.connect() as conn:
                from src.db.models import EventLog
                from sqlalchemy import select
                query = select(EventLog).order_by(EventLog.created_at.desc()).limit(tool_input.get("limit", 50))
                if tool_input.get("level"):
                    query = query.where(EventLog.level == tool_input["level"])
                if tool_input.get("agent_id"):
                    query = query.where(EventLog.agent_id == tool_input["agent_id"])
                rows = await conn.execute(query)
                return [{"level": r.level, "agent": r.agent_id, "msg": r.message, "at": r.created_at} for r in rows]

        elif tool_name == "create_github_pr" and self._github:
            branch = tool_input["branch"]
            await self._github.create_branch(branch)

            for file_info in tool_input.get("files", []):
                await self._github.create_or_update_file(
                    path=file_info["path"],
                    content=file_info["content"],
                    message=f"[Прораб] {tool_input['title']}",
                    branch=branch,
                )

            pr = await self._github.create_pull_request(
                title=tool_input["title"],
                body=tool_input["body"],
                head_branch=branch,
            )
            return {"pr_url": pr.html_url, "pr_number": pr.number}

        elif tool_name == "ping_external":
            import httpx
            service = tool_input["service"]
            if service == "anthropic_api":
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get("https://api.anthropic.com/v1/models", timeout=10)
                        return {"status": "ok" if resp.status_code < 500 else "degraded"}
                except Exception as e:
                    return {"status": "down", "error": str(e)}
            return {"status": "unknown", "service": service}

        elif tool_name == "read_file":
            import aiofiles
            import os
            path = tool_input["path"].lstrip("/")
            # Security: only allow reading project files
            safe_path = os.path.normpath(os.path.join("/home/user/many", path))
            if not safe_path.startswith("/home/user/many"):
                return {"error": "Access denied"}
            try:
                async with aiofiles.open(safe_path, "r") as f:
                    content = await f.read()
                return {"content": content[:5000], "truncated": len(content) > 5000}
            except FileNotFoundError:
                return {"error": f"File not found: {path}"}

        return await super()._call_tool(tool_name, tool_input)

    async def analyze_error(self, error_log: dict[str, Any]) -> str:
        """Analyze an error log entry and decide if PR is needed."""
        resp = await self._claude.complete(
            model=self._get_model(),
            system=self.get_system_prompt(),
            messages=[{
                "role": "user",
                "content": f"Вижу ошибку:\n{error_log}\n\nПроанализируй и скажи нужен ли патч.",
            }],
            max_tokens=1024,
        )
        return resp
