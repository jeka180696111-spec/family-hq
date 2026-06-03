from __future__ import annotations
import abc
from typing import Any, TYPE_CHECKING
from pydantic import BaseModel
import structlog

from src.utils.time import current_context_block
from src.utils.family import family_context_block

if TYPE_CHECKING:
    from src.integrations.claude_client import ClaudeClient
    from src.integrations.telegram_bots import BotManager
    from src.db.memory import SharedMemory
    from src.orchestrator.conversation import ConversationContext

log = structlog.get_logger()

class AgentResponse(BaseModel):
    text: str
    agent_id: str
    actions_taken: list[str] = []

class BaseAgent(abc.ABC):
    """
    Abstract base for all Family HQ agents.
    Each agent has its own Telegram bot identity and system prompt.
    """

    agent_id: str = ""
    emoji: str = "🤖"
    name: str = "Agent"

    def __init__(
        self,
        claude_client: "ClaudeClient",
        bot_manager: "BotManager",
        memory: "SharedMemory",
        chat_id: int,
    ) -> None:
        self._claude = claude_client
        self._bots = bot_manager
        self._memory = memory
        self._chat_id = chat_id
        self._log = structlog.get_logger().bind(agent_id=self.agent_id)

    @abc.abstractmethod
    def get_system_prompt(self) -> str:
        """Return the agent-specific system prompt (without shared time/team blocks)."""

    def _full_system_prompt(self) -> str:
        """System prompt with current date/time + family profile prepended."""
        return current_context_block() + family_context_block() + "\n\n" + self.get_system_prompt()

    @abc.abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """Return Claude tool definitions for this agent."""

    async def handle(
        self,
        message_text: str,
        sender_name: str,
        context: "ConversationContext",
        parsed_actions: list[dict] | None = None,
    ) -> AgentResponse:
        """
        Main message handler. Builds Claude request, processes tool calls,
        sends the response via Telegram.
        """
        import asyncio

        recent = await context.get_recent(10)
        history = context.format_for_agent(recent, self_agent_id=self.agent_id)
        self._current_sender = sender_name

        # Append current message
        history.append({"role": "user", "content": f"{sender_name}: {message_text}"})

        tools = self.get_tools()

        async def _typing_loop() -> None:
            """Keep '<agent> печатает...' visible to users while we think."""
            while True:
                try:
                    await self._bots.send_typing(self.agent_id, self._chat_id)
                except Exception:
                    pass
                await asyncio.sleep(4)

        typing_task = asyncio.create_task(_typing_loop())

        try:
            if tools:
                message = await self._claude.complete_with_tools(
                    model=self._get_model(),
                    system=self._full_system_prompt(),
                    messages=history,
                    tools=tools,
                    max_tokens=2048,
                )
                response_text, actions = await self._process_tool_calls(message, history)
            else:
                response_text = await self._claude.complete(
                    model=self._get_model(),
                    system=self._full_system_prompt(),
                    messages=history,
                    max_tokens=1024,
                )
                actions = []

            response_text = (response_text or "").strip()
            if not response_text:
                # If agent actually took actions (tool calls), produce a minimal
                # confirmation so user knows something happened. If no actions,
                # this is a genuine 'topic not mine' silence — stay quiet.
                if actions:
                    response_text = f"{self.emoji} Готово."
                else:
                    self._log.info("agent_silent", message=message_text[:50])
                    return AgentResponse(text="", agent_id=self.agent_id, actions_taken=actions)

            sent = await self.send(response_text)
            try:
                await context.save_message(
                    tg_message_id=getattr(sent, "message_id", 0) or 0,
                    user_id=None,
                    agent_id=self.agent_id,
                    text=response_text,
                )
            except Exception:
                self._log.exception("save_agent_response_failed")
            return AgentResponse(text=response_text, agent_id=self.agent_id, actions_taken=actions)

        except Exception:
            self._log.exception("handle_failed", message=message_text[:50])
            error_text = f"{self.emoji} Произошла ошибка при обработке. Попробуй ещё раз."
            await self.send(error_text)
            return AgentResponse(text=error_text, agent_id=self.agent_id)
        finally:
            typing_task.cancel()
            try:
                await typing_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _process_tool_calls(
        self, message: Any, history: list[dict]
    ) -> tuple[str, list[str]]:
        """Process tool use loop until final text response."""
        import anthropic
        actions_taken = []
        current_message = message
        current_history = list(history)

        while current_message.stop_reason == "tool_use":
            tool_results = []
            for block in current_message.content:
                if block.type == "tool_use":
                    result = await self._call_tool(block.name, block.input)
                    actions_taken.append(f"{block.name}({list(block.input.keys())})")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })

            current_history.append({"role": "assistant", "content": current_message.content})
            current_history.append({"role": "user", "content": tool_results})

            current_message = await self._claude.complete_with_tools(
                model=self._get_model(),
                system=self._full_system_prompt(),
                messages=current_history,
                tools=self.get_tools(),
                max_tokens=2048,
            )

        # Extract text from final response
        text_blocks = [b.text for b in current_message.content if hasattr(b, "text")]
        return "\n".join(text_blocks).strip(), actions_taken

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        """Dispatch a tool call to the appropriate handler. Override in subclasses."""
        self._log.warning("unknown_tool", tool_name=tool_name)
        return {"error": f"Unknown tool: {tool_name}"}

    def _get_model(self) -> str:
        from src.config import get_settings
        return get_settings().model_main

    async def send(self, text: str, reply_to: int | None = None) -> Any:
        """Send a message from this agent's bot to the HQ group. Returns the tg Message."""
        return await self._bots.send_message(
            agent_id=self.agent_id,
            chat_id=self._chat_id,
            text=text,
            reply_to_message_id=reply_to,
        )

    async def ask_other_agent(self, agent_id: str, question: str, agents: dict) -> str:
        """Query another agent's knowledge base (simplified: just ask Claude with their prompt)."""
        other = agents.get(agent_id)
        if not other:
            return f"Агент {agent_id} не найден."
        resp = await self._claude.complete(
            model=self._get_model(),
            system=other.get_system_prompt(),
            messages=[{"role": "user", "content": question}],
            max_tokens=512,
        )
        return resp
