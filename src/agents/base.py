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

    def _universal_tools(self) -> list[dict[str, Any]]:
        """Tools every agent gets automatically (Архивариус + forget/undo/help)."""
        return [
            {
                "name": "helper",
                "description": (
                    "Перечислить что ты умеешь и какие инструменты. Используй когда "
                    "спрашивают «что умеешь», «помощник», «справка», «помощь», «команды»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "forget_last_message",
                "description": (
                    "Удалить последнюю сохранённую запись пользователя из conversation memory. "
                    "Используй когда: «забудь последнее», «забудь что я писал», «отмени последнее»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "currency_rates",
                "description": (
                    "Курс валют от НБУ. Используй когда: «курс доллара», «евро сегодня», "
                    "«сколько грн за USD», «курс валют». Если Финн молчит — отвечай ты."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "currencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "ISO коды: USD, EUR, GBP, PLN... По умолчанию USD+EUR",
                        },
                    },
                },
            },
            {
                "name": "weather",
                "description": (
                    "Текущая погода или прогноз. Используй когда: «погода», «дождь сегодня», "
                    "«температура на улице», «холодно/жарко», «когда дождь». "
                    "По умолчанию — текущая погода в Одессе. "
                    "Если просят прогноз — укажи hours (3, 12, 24, 48)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["current", "forecast"], "default": "current"},
                        "city": {"type": "string", "description": "Город. По умолчанию Odesa,UA"},
                        "hours": {"type": "integer", "description": "Часов прогноза вперёд (для forecast)", "default": 24},
                    },
                },
            },
            {
                "name": "search_history",
                "description": (
                    "Поиск по всей семейной истории: Дневник Матвея, Здоровье, Прививки, "
                    "Прикорм, Достижения, Рост, Заметки + новостные посты + список покупок. "
                    "Используй когда спрашивают «когда последний раз X», «что было Y назад», "
                    "«как часто Z», «какая реакция на банан», «когда болело X»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Что искать. Без кавычек, ключевые слова: «банан», «температура», «нурофен», «прививка», «АТБ»",
                        },
                        "scope": {
                            "type": "string",
                            "enum": ["all", "diary", "health", "doctor", "feeding", "milestones", "growth", "notes", "news", "shopping"],
                            "description": "Где искать. По умолчанию all.",
                        },
                        "days": {
                            "type": "integer",
                            "description": "Глубина поиска в днях (по умолчанию 90)",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    def _full_tools(self) -> list[dict[str, Any]]:
        """Subclass tools + universal tools — used by handle() and tool loop."""
        return (self.get_tools() or []) + self._universal_tools()

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

        tools = self._full_tools()

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
                tools=self._full_tools(),
                max_tokens=2048,
            )

        # Extract text from final response
        text_blocks = [b.text for b in current_message.content if hasattr(b, "text")]
        return "\n".join(text_blocks).strip(), actions_taken

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        """Dispatch a tool call to the appropriate handler. Override in subclasses."""
        if tool_name == "helper":
            tools = self._full_tools()
            return {
                "agent": f"{self.emoji} {self.name}",
                "tools": [{"name": t["name"], "description": t.get("description", "")[:200]} for t in tools],
            }
        if tool_name == "forget_last_message":
            from sqlalchemy import delete, select
            from src.db.models import EventLog  # noqa: F401
            try:
                async with self._memory._engine.begin() as conn:
                    # Delete latest user message (no agent_id) from messages table
                    from src.db.models import Message
                    last = (await conn.execute(
                        select(Message).where(Message.agent_id.is_(None))
                        .order_by(Message.id.desc()).limit(1)
                    )).first()
                    if last:
                        await conn.execute(delete(Message).where(Message.id == last.id))
                        return {"success": True, "deleted_text": (last.text or "")[:120]}
                    return {"success": False, "error": "Нет сообщений для удаления"}
            except Exception as e:
                return {"error": str(e)}
        if tool_name == "currency_rates":
            try:
                from src.integrations.currency import NBUClient
                client = NBUClient()
                currencies = tool_input.get("currencies") or ["USD", "EUR"]
                rates = await client.rates(currencies=currencies)
                return {"source": "НБУ", "rates": rates}
            except Exception as e:
                return {"error": str(e)}

        if tool_name == "weather":
            try:
                from src.config import get_settings
                from src.integrations.weather import WeatherClient
                client = WeatherClient.from_settings(get_settings())
                if not client:
                    return {
                        "error": "Погода не настроена",
                        "setup": "Получи ключ на https://openweathermap.org/api → "
                                 "добавь OPENWEATHER_API_KEY в Railway env",
                    }
                mode = tool_input.get("mode", "current")
                city = tool_input.get("city")
                if mode == "forecast":
                    return {"forecast": await client.forecast(city, int(tool_input.get("hours", 24)))}
                return await client.current(city)
            except Exception as e:
                return {"error": str(e)}

        if tool_name == "search_history":
            from src.integrations.history_search import search_history
            sheets = getattr(self, "_sheets", None)
            return await search_history(
                query=tool_input.get("query", ""),
                memory=self._memory,
                sheets_client=sheets,
                scope=tool_input.get("scope", "all"),
                days=int(tool_input.get("days", 90)),
            )
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
