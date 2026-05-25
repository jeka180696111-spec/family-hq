from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock

from src.orchestrator.parser import MessageParser, ParsedMessage, ParsedAction


@pytest.fixture
def mock_claude():
    return AsyncMock()


@pytest.fixture
def parser(mock_claude):
    return MessageParser(mock_claude, "claude-haiku-4-5-20251001")


@pytest.mark.asyncio
async def test_parse_sleep_message(parser, mock_claude):
    """Parse baby sleep message."""
    mock_claude.complete.return_value = json.dumps({
        "actions": [{"type": "baby_sleep_start", "time": "14:30"}],
        "needs_clarification": False,
        "clarification_questions": [],
        "confidence": 0.95,
    })
    result = await parser.parse("малыш уснул в 14:30")
    assert isinstance(result, ParsedMessage)
    assert len(result.actions) == 1
    assert result.actions[0].type == "baby_sleep_start"
    assert result.confidence == 0.95


@pytest.mark.asyncio
async def test_parse_expense_message(parser, mock_claude):
    """Parse expense message."""
    mock_claude.complete.return_value = json.dumps({
        "actions": [{"type": "expense", "amount": 89, "currency": "UAH", "category": "малыш", "description": "смесь"}],
        "needs_clarification": False,
        "clarification_questions": [],
        "confidence": 0.98,
    })
    result = await parser.parse("смесь 89 грн")
    assert result.actions[0].type == "expense"


@pytest.mark.asyncio
async def test_parse_multi_action(parser, mock_claude):
    """Parse message with multiple actions."""
    mock_claude.complete.return_value = json.dumps({
        "actions": [
            {"type": "baby_sleep_start", "time": "14:30"},
            {"type": "expense", "amount": 420, "currency": "UAH", "category": "гигиена", "description": "подгузники"},
        ],
        "needs_clarification": False,
        "clarification_questions": [],
        "confidence": 0.92,
    })
    result = await parser.parse("малыш уснул в 14:30, купила подгузники 420 грн")
    assert len(result.actions) == 2


@pytest.mark.asyncio
async def test_parse_needs_clarification(parser, mock_claude):
    """Medicine without dose should need clarification."""
    mock_claude.complete.return_value = json.dumps({
        "actions": [{"type": "baby_medicine", "name": "нурофен"}],
        "needs_clarification": True,
        "clarification_questions": ["Какая доза?"],
        "confidence": 0.7,
    })
    result = await parser.parse("дала нурофен")
    assert result.needs_clarification is True
    assert len(result.clarification_questions) == 1


@pytest.mark.asyncio
async def test_parse_ukrainian_language(parser, mock_claude):
    """Should handle Ukrainian language input."""
    mock_claude.complete.return_value = json.dumps({
        "actions": [{"type": "baby_sleep_start", "time": "15:00"}],
        "needs_clarification": False,
        "clarification_questions": [],
        "confidence": 0.9,
    })
    result = await parser.parse("малюк заснув о 15:00")
    assert result.actions[0].type == "baby_sleep_start"


@pytest.mark.asyncio
async def test_parse_error_returns_empty(parser, mock_claude):
    """On API error, should return empty ParsedMessage."""
    mock_claude.complete.side_effect = Exception("timeout")
    result = await parser.parse("test")
    assert isinstance(result, ParsedMessage)
    assert result.actions == []
    assert result.needs_clarification is False
