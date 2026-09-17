"""Add setup-owned encrypted Proxmox credentials and registration attempts.

Existing credentials are never imported by this migration. No existing table,
operation, lock, account, or historical artifact is modified.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260917_0030"
down_revision = "20260824_0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "proxmox_connections",
        sa.Column("slot", sa.Integer(), primary_key=True),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("cluster_id", sa.String(160), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("active_revision_id", sa.String(36)),
        sa.Column("admission", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("slot = 1", name="ck_proxmox_connection_singleton"),
        sa.CheckConstraint("source in ('legacy_env', 'managed')", name="ck_proxmox_connection_source"),
        sa.CheckConstraint("admission in ('open', 'closed')", name="ck_proxmox_connection_admission"),
        sa.UniqueConstraint("connection_id", name="uq_proxmox_connection_id"),
    )
    op.create_table(
        "proxmox_credentials",
        sa.Column("revision_id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("proxmox_connections.connection_id"), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state in ('pending', 'active', 'retiring', 'revoked')", name="ck_proxmox_credential_state"),
        sa.CheckConstraint("format_version = 1", name="ck_proxmox_credential_format"),
        sa.UniqueConstraint("key_id", "nonce", name="uq_proxmox_credential_nonce"),
    )
    op.create_index("uq_proxmox_credential_active", "proxmox_credentials", ["connection_id"], unique=True,
                    postgresql_where=sa.text("state = 'active'"), sqlite_where=sa.text("state = 'active'"))
    op.create_table(
        "proxmox_registration_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("proxmox_connections.connection_id"), nullable=False),
        sa.Column("operation_id", sa.String(160), sa.ForeignKey("operations.operation_id"), nullable=False, unique=True),
        sa.Column("revocation_operation_id", sa.String(160), sa.ForeignKey("operations.operation_id")),
        sa.Column("actor_id", sa.String(80), nullable=False),
        sa.Column("idempotency_digest", sa.String(64), nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("intent", sa.JSON(), nullable=False),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("expected_connection_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("proxmox_credentials.revision_id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("connection_id", "idempotency_digest", name="uq_proxmox_registration_idempotency"),
    )
    op.create_index("uq_proxmox_registration_unresolved", "proxmox_registration_attempts", ["connection_id"], unique=True,
                    postgresql_where=sa.text("resolved = false"), sqlite_where=sa.text("resolved = 0"))


def downgrade():
    raise RuntimeError("Credential/audit preservation requires a reviewed forward migration; destructive downgrade is disabled.")
