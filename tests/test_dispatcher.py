from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.dispatcher import Dispatcher, DispatchResult, AgentTask


@pytest.fixture
def mock_claude():
    client = AsyncMock()
    return client


@pytest.fixture
def dispatcher(mock_claude):
    return Dispatcher(mock_claude, "claude-haiku-4-5-20251001")


ACTIVE_AGENTS = ["nanny", "news", "finance", "calendar", "cook", "health", "devops"]


@pytest.mark.asyncio
async def test_dispatch_baby_message(dispatcher, mock_claude):
    """Baby sleep message should go to nanny."""
    mock_claude.complete.return_value = json.dumps({
        "agents": [{"id": "nanny", "priority": "high", "reason": "запись о сне"}],
        "is_critical": False,
        "is_settings_command": False,
    })
    result = await dispatcher.dispatch("малыш уснул в 14:30", "Мама", ACTIVE_AGENTS)
    assert isinstance(result, DispatchResult)
    assert len(result.tasks) == 1
    assert result.tasks[0].agent_id == "nanny"
    assert result.tasks[0].priority == "high"


@pytest.mark.asyncio
async def test_dispatch_expense_message(dispatcher, mock_claude):
    """Expense message should go to finance."""
    mock_claude.complete.return_value = json.dumps({
        "agents": [{"id": "finance", "priority": "high", "reason": "трата"}],
        "is_critical": False,
        "is_settings_command": False,
    })
    result = await dispatcher.dispatch("купила подгузники за 420 грн", "Мама", ACTIVE_AGENTS)
    assert any(t.agent_id == "finance" for t in result.tasks)


@pytest.mark.asyncio
async def test_dispatch_multi_agent(dispatcher, mock_claude):
    """Combined message should go to multiple agents."""
    mock_claude.complete.return_value = json.dumps({
        "agents": [
            {"id": "nanny", "priority": "high", "reason": "еда малыша"},
            {"id": "finance", "priority": "low", "reason": "трата"},
        ],
        "is_critical": False,
        "is_settings_command": False,
    })
    result = await dispatcher.dispatch(
        "купила пюре за 89 грн, дала малышу 50г",
        "Мама",
        ACTIVE_AGENTS,
    )
    agent_ids = [t.agent_id for t in result.tasks]
    assert "nanny" in agent_ids
    assert "finance" in agent_ids


@pytest.mark.asyncio
async def test_dispatch_critical_alert(dispatcher, mock_claude):
    """Air raid alert should be critical."""
    mock_claude.complete.return_value = json.dumps({
        "agents": [{"id": "news", "priority": "critical", "reason": "тревога"}],
        "is_critical": True,
        "is_settings_command": False,
    })
    result = await dispatcher.dispatch("тревога в одессе", "Система", ACTIVE_AGENTS)
    assert result.is_critical is True
    assert result.tasks[0].agent_id == "news"
    assert result.tasks[0].priority == "critical"


@pytest.mark.asyncio
async def test_dispatch_fallback_on_error(dispatcher, mock_claude):
    """On API error, should fall back to nanny."""
    mock_claude.complete.side_effect = Exception("API timeout")
    result = await dispatcher.dispatch("test message", "User", ACTIVE_AGENTS)
    assert len(result.tasks) == 1
    assert result.tasks[0].agent_id == "nanny"
    assert result.tasks[0].reason == "error_fallback"


@pytest.mark.asyncio
async def test_dispatch_filters_inactive_agents(dispatcher, mock_claude):
    """Agents not in active list should be filtered out."""
    mock_claude.complete.return_value = json.dumps({
        "agents": [
            {"id": "housekeeper", "priority": "high", "reason": "запрос"},
            {"id": "nanny", "priority": "normal", "reason": "малыш"},
        ],
        "is_critical": False,
        "is_settings_command": False,
    })
    result = await dispatcher.dispatch("message", "User", ACTIVE_AGENTS)
    # housekeeper not in active list, should be filtered
    assert all(t.agent_id != "housekeeper" for t in result.tasks)
    assert any(t.agent_id == "nanny" for t in result.tasks)


@pytest.mark.asyncio
async def test_dispatch_invalid_json_fallback(dispatcher, mock_claude):
    """Invalid JSON response should fall back gracefully."""
    mock_claude.complete.return_value = "not json at all"
    result = await dispatcher.dispatch("message", "User", ACTIVE_AGENTS)
    assert len(result.tasks) >= 1
