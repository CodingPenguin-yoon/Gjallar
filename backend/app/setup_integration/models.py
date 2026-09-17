"""Setup-owned connection, encrypted revision, and registration persistence."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProxmoxConnectionRecord(Base):
    __tablename__ = "proxmox_connections"
    __table_args__ = (
        CheckConstraint("slot = 1", name="ck_proxmox_connection_singleton"),
        CheckConstraint("source in ('legacy_env', 'managed')", name="ck_proxmox_connection_source"),
        CheckConstraint("admission in ('open', 'closed')", name="ck_proxmox_connection_admission"),
        UniqueConstraint("connection_id", name="uq_proxmox_connection_id"),
    )
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(36), nullable=False)
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="legacy_env")
    active_revision_id: Mapped[str | None] = mapped_column(String(36))
    admission: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProxmoxCredentialRecord(Base):
    __tablename__ = "proxmox_credentials"
    __table_args__ = (
        CheckConstraint("state in ('pending', 'active', 'retiring', 'revoked')", name="ck_proxmox_credential_state"),
        CheckConstraint("format_version = 1", name="ck_proxmox_credential_format"),
        UniqueConstraint("key_id", "nonce", name="uq_proxmox_credential_nonce"),
        Index("uq_proxmox_credential_active", "connection_id", unique=True,
              postgresql_where=text("state = 'active'"),
              sqlite_where=text("state = 'active'")),
    )
    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("proxmox_connections.connection_id"), nullable=False)
    # Includes endpoint, owner/token identity, CA, features and selected scope.
    # Authenticated as AAD; never includes password, ticket, OTP or token value.
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    format_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProxmoxRegistrationRecord(Base):
    __tablename__ = "proxmox_registration_attempts"
    __table_args__ = (
        UniqueConstraint("connection_id", "idempotency_digest", name="uq_proxmox_registration_idempotency"),
        Index("uq_proxmox_registration_unresolved", "connection_id", unique=True,
              postgresql_where=text("resolved = false"),
              sqlite_where=text("resolved = 0")),
    )
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("proxmox_connections.connection_id"), nullable=False)
    operation_id: Mapped[str] = mapped_column(ForeignKey("operations.operation_id"), nullable=False, unique=True)
    revocation_operation_id: Mapped[str | None] = mapped_column(ForeignKey("operations.operation_id"))
    actor_id: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    intent: Mapped[dict] = mapped_column(JSON, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False, default="prepared")
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expected_connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("proxmox_credentials.revision_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
