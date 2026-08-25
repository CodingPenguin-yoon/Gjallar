"""Remove empty DRS persistence contracts and narrow shared operation locks.

Revision ID: 20260824_0029
Revises: 20260721_0028
Create Date: 2026-08-24 18:00:00.000000
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "20260824_0029"
down_revision = "20260721_0028"
branch_labels = None
depends_on = None


DRS_TABLES = (
    "drs_reconciliation_events",
    "drs_migration_jobs",
    "drs_approval_packets",
    "vm_migration_policy_events",
    "vm_migration_policies",
    "vm_identity_observations",
    "vm_identities",
)

LOCKED_TABLES = (*DRS_TABLES, "operation_locks")

INCOMPATIBLE_LOCK_PREDICATE = """
operation_type not in ('vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown')
or scope_type != 'proxmox_locator'
or vm_identity_id is not null
or source_node_id is not null
or target_node_id is not null
"""


def _acquire_write_blocking_lock(connection: sa.Connection) -> None:
    dialect_name = connection.dialect.name
    if dialect_name == "sqlite":
        # Alembic opens a logical per-revision transaction for SQLite, but
        # sqlite3 does not emit BEGIN for a leading SELECT or DDL statement.
        # BEGIN IMMEDIATE obtains the database write reservation before the
        # hard-zero reads and makes the DDL plus Alembic version stamp one
        # rollback-capable transaction.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        return
    if dialect_name == "postgresql":
        table_names = ", ".join(LOCKED_TABLES)
        connection.execute(
            sa.text(
                f"lock table {table_names} in share row exclusive mode"
            )
        )
        return
    raise RuntimeError(f"Unsupported DRS schema retirement dialect: {dialect_name}")


def _retained_drs_rows(connection: sa.Connection) -> dict[str, int]:
    retained: dict[str, int] = {}
    for table_name in DRS_TABLES:
        count = int(
            connection.execute(
                sa.text(f"select count(*) from {table_name}")
            ).scalar_one()
        )
        if count:
            retained[table_name] = count

    incompatible_locks = int(
        connection.execute(
            sa.text(
                "select count(*) from operation_locks where "
                + INCOMPATIBLE_LOCK_PREDICATE
            )
        ).scalar_one()
    )
    if incompatible_locks:
        retained["operation_locks"] = incompatible_locks
    return retained


def _assert_empty_drs_contract(connection: sa.Connection) -> None:
    retained = _retained_drs_rows(connection)
    if not retained:
        return
    summary = ", ".join(f"{name}={count}" for name, count in retained.items())
    raise RuntimeError(
        "DRS schema retirement requires an empty DRS contract; "
        f"retained rows: {summary}. Archive or retire the data through a "
        "separately approved forward migration before retrying."
    )


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("DRS schema retirement requires an online hard-zero preflight")

    connection = op.get_bind()
    _acquire_write_blocking_lock(connection)
    _assert_empty_drs_contract(connection)

    for index_name in (
        "uq_operation_locks_open_scope",
        "ix_operation_locks_cluster_identity_status",
        "ix_operation_locks_locator_status",
        "ix_operation_locks_route_status",
    ):
        op.drop_index(index_name, table_name="operation_locks")

    with op.batch_alter_table("operation_locks") as batch_op:
        batch_op.drop_constraint("ck_operation_locks_operation_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_locks_operation_type",
            "operation_type in ('vm_start', 'vm_create', 'guided_qm_vm_unlock', 'vm_shutdown')",
        )
        batch_op.drop_constraint("ck_operation_locks_scope_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_locks_scope_type",
            "scope_type = 'proxmox_locator'",
        )
        batch_op.drop_column("vm_identity_id")
        batch_op.drop_column("source_node_id")
        batch_op.drop_column("target_node_id")

    for table_name in DRS_TABLES:
        op.drop_table(table_name)


def downgrade() -> None:
    raise RuntimeError(
        "DRS schema retirement is roll-forward only; use a separately approved corrective migration"
    )
