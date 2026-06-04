"""SQLAlchemy 2.0 async ORM models for Family HQ.

Tables: users, messages, pending_queue, approval_requests, news_channels,
        news_posts, active_alerts, user_rules, agent_settings, event_log,
        external_health, family_members, health_records, introduced_foods,
        agents, agent_hiring_requests, agent_archive
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    tg_user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # 'owner'|'pending'|'guest'|'denied'
    can_approve: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "tg_message_id", name="uq_messages_chat_msg"),
        Index("idx_messages_date", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_media: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    media_path: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[str] = mapped_column(String, nullable=False)
    parsed_actions: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# pending_queue
# ---------------------------------------------------------------------------


class PendingQueue(Base):
    __tablename__ = "pending_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("messages.id"), nullable=True
    )
    intended_agents: Mapped[str] = mapped_column(Text, nullable=False)
    enqueued_at: Mapped[str] = mapped_column(String, nullable=False)
    processed_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# approval_requests
# ---------------------------------------------------------------------------


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    action_data: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # 'pending'|'approved'|'denied'|'expired'
    requested_at: Mapped[str] = mapped_column(String, nullable=False)
    resolved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# news_channels
# ---------------------------------------------------------------------------


class NewsChannel(Base):
    __tablename__ = "news_channels"

    channel_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'critical'|'important'|'background'
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(
        String, nullable=False, default="silent"
    )  # 'alert'|'silent'|'digest'
    added_at: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


# ---------------------------------------------------------------------------
# news_posts
# ---------------------------------------------------------------------------


class NewsPost(Base):
    __tablename__ = "news_posts"
    __table_args__ = (
        UniqueConstraint("channel_id", "tg_message_id", name="uq_news_posts_chan_msg"),
        Index("idx_news_date", "date"),
        Index("idx_news_alerts", "is_alert", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("news_channels.channel_id"), nullable=True
    )
    tg_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)
    is_alert: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alert_region: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# active_alerts
# ---------------------------------------------------------------------------


class ActiveAlert(Base):
    __tablename__ = "active_alerts"

    region: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    sources: Mapped[str] = mapped_column(Text, nullable=False)
    announced_at: Mapped[str] = mapped_column(String, nullable=False)
    last_update_at: Mapped[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# shopping_list — geo-aware shopping reminders
# ---------------------------------------------------------------------------


class ShoppingItem(Base):
    __tablename__ = "shopping_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[str | None] = mapped_column(String, nullable=True)
    place: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # 'АТБ' | 'Сільпо' | 'аптека' | None=anywhere
    added_by: Mapped[str | None] = mapped_column(String, nullable=True)
    added_at: Mapped[str] = mapped_column(String, nullable=False)
    notified_at: Mapped[str | None] = mapped_column(String, nullable=True)
    done_at: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# user_rules
# ---------------------------------------------------------------------------


class UserRule(Base):
    __tablename__ = "user_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    rule_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'classification'|'preference'|'restriction'
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.tg_user_id"), nullable=True
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


# ---------------------------------------------------------------------------
# agent_settings
# ---------------------------------------------------------------------------


class AgentSetting(Base):
    __tablename__ = "agent_settings"
    __table_args__ = (PrimaryKeyConstraint("agent_id", "key"),)

    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# event_log
# ---------------------------------------------------------------------------


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (Index("idx_log_level_date", "level", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    component: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# external_health
# ---------------------------------------------------------------------------


class ExternalHealth(Base):
    __tablename__ = "external_health"

    service: Mapped[str] = mapped_column(String, primary_key=True)
    last_check_at: Mapped[str] = mapped_column(String, nullable=False)
    last_status: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'ok'|'degraded'|'down'
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# family_members
# ---------------------------------------------------------------------------


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    birthdate: Mapped[str | None] = mapped_column(String, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    chronic: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


# ---------------------------------------------------------------------------
# health_records
# ---------------------------------------------------------------------------


class HealthRecord(Base):
    __tablename__ = "health_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("family_members.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'symptom'|'medication'|'visit'|'vaccine'
    description: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# introduced_foods
# ---------------------------------------------------------------------------


class IntroducedFood(Base):
    __tablename__ = "introduced_foods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    food: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    first_tried_at: Mapped[str] = mapped_column(String, nullable=False)
    times_tried: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reaction: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    emoji: Mapped[str] = mapped_column(String, nullable=False)
    bot_token_env: Mapped[str] = mapped_column(String, nullable=False)
    zone: Mapped[str] = mapped_column(String, nullable=False)
    verbosity: Mapped[str] = mapped_column(
        String, nullable=False, default="on_demand"
    )  # 'silent'|'on_demand'|'proactive'
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # 'active'|'archived'|'rolled_back'
    hired_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str | None] = mapped_column(String, nullable=True)
    archive_path: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# agent_hiring_requests
# ---------------------------------------------------------------------------


class AgentHiringRequest(Base):
    __tablename__ = "agent_hiring_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.tg_user_id"), nullable=True
    )
    proposed_id: Mapped[str] = mapped_column(String, nullable=False)
    proposed_name: Mapped[str] = mapped_column(String, nullable=False)
    requirements: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(
        String, nullable=False, default="interview"
    )  # 'interview'|'coding'|'pr_created'|'awaiting_manual'|'merged'|'deployed'|'cancelled'
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# agent_archive
# ---------------------------------------------------------------------------


class AgentArchive(Base):
    __tablename__ = "agent_archive"

    agent_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    archived_at: Mapped[str] = mapped_column(String, nullable=False)
    archived_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.tg_user_id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    data_path: Mapped[str] = mapped_column(String, nullable=False)
    restorable_until: Mapped[str] = mapped_column(String, nullable=False)
