from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncContextManager
from contextlib import asynccontextmanager

from src.orchestrator.access_control import AccessControl


OWNER_HUSBAND = 111
OWNER_WIFE = 222
STRANGER = 999


@pytest.fixture
def mock_memory():
    memory = MagicMock()
    return memory


@pytest.fixture
def access_control(mock_memory):
    return AccessControl(mock_memory, [OWNER_HUSBAND, OWNER_WIFE])


def test_is_owner_husband(access_control):
    assert access_control.is_owner(OWNER_HUSBAND) is True


def test_is_owner_wife(access_control):
    assert access_control.is_owner(OWNER_WIFE) is True


def test_is_not_owner_stranger(access_control):
    assert access_control.is_owner(STRANGER) is False


def test_get_other_owner_from_husband(access_control):
    other = access_control.get_other_owner(OWNER_HUSBAND)
    assert other == OWNER_WIFE


def test_get_other_owner_from_wife(access_control):
    other = access_control.get_other_owner(OWNER_WIFE)
    assert other == OWNER_HUSBAND


def test_get_other_owner_single_owner():
    """If only one owner, no other owner available."""
    memory = MagicMock()
    ac = AccessControl(memory, [OWNER_HUSBAND])
    other = ac.get_other_owner(OWNER_HUSBAND)
    assert other is None


def test_requires_approval_delete(access_control):
    assert access_control.requires_approval("delete_record") is True


def test_requires_approval_patch(access_control):
    assert access_control.requires_approval("apply_patch") is True


def test_does_not_require_approval_normal(access_control):
    assert access_control.requires_approval("write_diary") is False
    assert access_control.requires_approval("read_data") is False


def test_critical_action_types_complete(access_control):
    """All spec-defined critical actions should require approval."""
    critical_actions = [
        "delete_record",
        "modify_budget",
        "delete_calendar_event",
        "dangerous_medicine_dose",
        "change_agent_settings",
        "apply_patch",
        "fire_agent",
    ]
    for action in critical_actions:
        assert access_control.requires_approval(action), f"{action} should require approval"
