"""Modelo de dados do DocOps."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from .db import Base, JSONType


def now():
    return datetime.now(timezone.utc)


ROLES = ("client", "viewer", "analyst", "admin")
ROLE_LEVEL = {r: i for i, r in enumerate(ROLES)}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    logo: Mapped[str | None] = deferred(mapped_column(Text, nullable=True))  # data URL
    color: Mapped[str] = mapped_column(String(16), default="#4a7a37")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="viewer")

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")


class AwsAccount(Base):
    __tablename__ = "aws_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "account_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[str] = mapped_column(String(12))
    alias: Mapped[str] = mapped_column(String(120))
    role_arn: Mapped[str | None] = mapped_column(String(300), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    regions: Mapped[list | None] = mapped_column(JSONType, nullable=True)  # None = todas as habilitadas
    environment: Mapped[str] = mapped_column(String(40), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    aws_account_id: Mapped[int | None] = mapped_column(ForeignKey("aws_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    account_id: Mapped[str] = mapped_column(String(12), index=True, default="")
    alias: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(20))  # assume_role | upload
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual | schedule | upload
    triggered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    diff: Mapped[dict | None] = deferred(mapped_column(JSONType, nullable=True))
    payload: Mapped[dict | None] = deferred(mapped_column(JSONType, nullable=True))


class Note(Base):
    """Anotações por recurso e tratativas de achados (chave 'finding|<id>')."""
    __tablename__ = "notes"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(600))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TenantDoc(Base):
    """Documentação do ambiente (campos gerais, fichas das contas, histórico de mudanças)."""
    __tablename__ = "tenant_docs"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class TenantState(Base):
    """Último conjunto de achados calculado para o cliente (base para alertas de achados novos)."""
    __tablename__ = "tenant_state"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    findings: Mapped[list] = mapped_column(JSONType, default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TenantSetting(Base):
    __tablename__ = "tenant_settings"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    teams_webhook: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_severities: Mapped[list] = mapped_column(JSONType, default=lambda: ["critical", "high"])
    alert_on_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_on_changes: Mapped[bool] = mapped_column(Boolean, default=False)


class TenantAIConfig(Base):
    """Configuração de provedor de IA por cliente."""
    __tablename__ = "tenant_ai_configs"
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="gpt")
    model: Mapped[str] = mapped_column(String(120), default="gpt-4o-mini")
    base_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    cron: Mapped[str] = mapped_column(String(100))
    account_ids: Mapped[list | None] = mapped_column(JSONType, nullable=True)  # ids de aws_accounts; None = todas ativas
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_email: Mapped[str] = mapped_column(String(254), default="")
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
