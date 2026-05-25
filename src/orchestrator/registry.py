from __future__ import annotations
from pydantic import BaseModel
import structlog

log = structlog.get_logger()

class AgentMeta(BaseModel):
    agent_id: str
    name: str
    emoji: str
    bot_token_env: str
    zone: str
    verbosity: str  # 'silent' | 'on_demand' | 'proactive'
    status: str     # 'active' | 'archived' | 'rolled_back'

class AgentRegistry:
    """
    Dynamic registry of all agents.
    Loaded at startup, updated on hire/fire.
    Dispatcher uses this to know who's available.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentMeta] = {}

    def register(self, meta: AgentMeta) -> None:
        self._agents[meta.agent_id] = meta
        log.info("agent_registered", agent_id=meta.agent_id, status=meta.status)

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
        log.info("agent_unregistered", agent_id=agent_id)

    def update_verbosity(self, agent_id: str, level: str) -> None:
        if agent_id in self._agents:
            self._agents[agent_id] = self._agents[agent_id].model_copy(
                update={"verbosity": level}
            )

    def list_active(self) -> list[AgentMeta]:
        return [a for a in self._agents.values() if a.status == "active"]

    def list_archived(self) -> list[AgentMeta]:
        return [a for a in self._agents.values() if a.status == "archived"]

    def get(self, agent_id: str) -> AgentMeta | None:
        return self._agents.get(agent_id)

    def active_ids(self) -> list[str]:
        return [a.agent_id for a in self.list_active()]

    @classmethod
    async def load_from_db(cls, memory) -> "AgentRegistry":
        """Load agent metadata from the agents table."""
        registry = cls()
        async with memory._engine.connect() as conn:
            from src.db.models import AgentModel
            from sqlalchemy import select
            rows = await conn.execute(
                select(AgentModel).where(AgentModel.status == "active")
            )
            for row in rows:
                registry.register(AgentMeta(
                    agent_id=row.agent_id,
                    name=row.name,
                    emoji=row.emoji,
                    bot_token_env=row.bot_token_env,
                    zone=row.zone,
                    verbosity=row.verbosity,
                    status=row.status,
                ))
        return registry
