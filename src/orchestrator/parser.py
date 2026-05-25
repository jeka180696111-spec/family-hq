from __future__ import annotations
import json
from typing import Any
from pydantic import BaseModel
import structlog

from src.integrations.claude_client import ClaudeClient
from src.prompts.parser import PARSER_SYSTEM

log = structlog.get_logger()

class ParsedAction(BaseModel):
    type: str
    # All other fields are flexible
    model_config = {"extra": "allow"}

class ParsedMessage(BaseModel):
    actions: list[ParsedAction]
    needs_clarification: bool = False
    clarification_questions: list[str] = []
    confidence: float = 1.0

class MessageParser:
    """
    Extracts structured actions from free-form messages.
    Uses Claude Haiku for speed and cost.
    """

    def __init__(self, claude_client: ClaudeClient, model: str) -> None:
        self._claude = claude_client
        self._model = model

    async def parse(
        self,
        text: str,
        has_image: bool = False,
    ) -> ParsedMessage:
        """
        Parse a message into structured actions.
        Returns empty ParsedMessage if parsing fails.
        """
        content = text
        if has_image:
            content += "\n[Сообщение содержит изображение]"

        try:
            response = await self._claude.complete(
                model=self._model,
                system=PARSER_SYSTEM,
                messages=[{"role": "user", "content": content}],
                max_tokens=1024,
            )
            data = json.loads(response)
            return ParsedMessage(
                actions=[ParsedAction(**a) for a in data.get("actions", [])],
                needs_clarification=data.get("needs_clarification", False),
                clarification_questions=data.get("clarification_questions", []),
                confidence=data.get("confidence", 1.0),
            )
        except Exception:
            log.exception("parse_failed", text=text[:50])
            return ParsedMessage(actions=[], needs_clarification=False)
