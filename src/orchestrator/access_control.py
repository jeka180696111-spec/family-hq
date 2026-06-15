from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Any
from pydantic import BaseModel
import structlog

from src.db.memory import SharedMemory
from src.utils.time import iso_now, KYIV_TZ

log = structlog.get_logger()

class ApprovalRequest(BaseModel):
    id: int
    requester_id: int
    approver_id: int
    action_type: str
    action_data: dict[str, Any]
    status: str
    requested_at: str
    expires_at: str

class AccessControl:
    """
    Checks user permissions and manages double-confirmation flow.

    Critical operations require approval from the OTHER owner.
    The initiator cannot approve their own request.
    """

    CRITICAL_ACTION_TYPES = {
        "delete_record",
        "modify_budget",
        "delete_calendar_event",
        "dangerous_medicine_dose",
        "change_agent_settings",
        "apply_patch",
        "fire_agent",
    }

    def __init__(self, memory: SharedMemory, owner_ids: list[int]) -> None:
        self._memory = memory
        self._owner_ids = owner_ids

    def is_owner(self, user_id: int) -> bool:
        """Check if user is an authorized owner."""
        return user_id in self._owner_ids

    def get_other_owner(self, requester_id: int) -> int | None:
        """Get the other owner's ID for approval requests.

        If `requester_id` is not itself an owner we return None — a
        non-owner caller has no business spawning approval requests
        against owners (would allow a stranger to keep nagging Marina
        or Eugene with /approve buttons)."""
        if requester_id not in self._owner_ids:
            return None
        for owner_id in self._owner_ids:
            if owner_id != requester_id:
                return owner_id
        return None

    def requires_approval(self, action_type: str) -> bool:
        """Check if an action requires double confirmation."""
        return action_type in self.CRITICAL_ACTION_TYPES

    async def create_approval_request(
        self,
        requester_id: int,
        action_type: str,
        action_data: dict[str, Any],
    ) -> ApprovalRequest | None:
        """
        Create an approval request for a critical action.
        Returns None if no second owner available.
        """
        approver_id = self.get_other_owner(requester_id)
        if not approver_id:
            log.warning("no_approver_available", requester_id=requester_id)
            return None

        now = datetime.now(KYIV_TZ)
        expires = now + timedelta(hours=24)

        async with self._memory._engine.begin() as conn:
            from src.db.models import ApprovalRequestModel
            from sqlalchemy import insert
            result = await conn.execute(
                insert(ApprovalRequestModel).values(
                    requester_id=requester_id,
                    approver_id=approver_id,
                    action_type=action_type,
                    action_data=json.dumps(action_data),
                    status="pending",
                    requested_at=now.isoformat(),
                    expires_at=expires.isoformat(),
                ).returning(ApprovalRequestModel.id)
            )
            request_id = result.scalar_one()

        return ApprovalRequest(
            id=request_id,
            requester_id=requester_id,
            approver_id=approver_id,
            action_type=action_type,
            action_data=action_data,
            status="pending",
            requested_at=now.isoformat(),
            expires_at=expires.isoformat(),
        )

    async def resolve_approval(
        self,
        request_id: int,
        approver_id: int,
        approved: bool,
    ) -> bool:
        """
        Approve or deny a pending request.
        Returns True if resolved successfully.
        """
        status = "approved" if approved else "denied"
        async with self._memory._engine.begin() as conn:
            from src.db.models import ApprovalRequestModel
            from sqlalchemy import update, select
            row = await conn.execute(
                select(ApprovalRequestModel).where(
                    ApprovalRequestModel.id == request_id,
                    ApprovalRequestModel.approver_id == approver_id,
                    ApprovalRequestModel.status == "pending",
                )
            )
            req = row.first()
            if not req:
                return False
            await conn.execute(
                update(ApprovalRequestModel)
                .where(ApprovalRequestModel.id == request_id)
                .values(status=status, resolved_at=iso_now())
            )
        log.info("approval_resolved", request_id=request_id, status=status)
        return True

    async def get_pending_approvals(self, approver_id: int) -> list[ApprovalRequest]:
        """Get all pending approval requests for an approver."""
        async with self._memory._engine.connect() as conn:
            from src.db.models import ApprovalRequestModel
            from sqlalchemy import select
            rows = await conn.execute(
                select(ApprovalRequestModel).where(
                    ApprovalRequestModel.approver_id == approver_id,
                    ApprovalRequestModel.status == "pending",
                )
            )
            return [
                ApprovalRequest(
                    id=row.id,
                    requester_id=row.requester_id,
                    approver_id=row.approver_id,
                    action_type=row.action_type,
                    action_data=json.loads(row.action_data),
                    status=row.status,
                    requested_at=row.requested_at,
                    expires_at=row.expires_at,
                )
                for row in rows
            ]
