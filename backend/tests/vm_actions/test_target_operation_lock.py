"""Tests for shared target operation lock helper."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.operations.target_lock import (
    TargetOperationLockBusy,
    acquire_target_operation_lock,
    get_target_operation_lock,
    release_target_operation_lock,
    release_target_operation_lock_for_owner,
)


def test_target_operation_lock_blocks_same_target_until_released():
    target_id = f"node-a:{uuid.uuid4().hex}"
    handle = acquire_target_operation_lock("vm", target_id, "owner-a")

    try:
        assert "path" not in handle.to_dict()
        with pytest.raises(TargetOperationLockBusy) as raised:
            acquire_target_operation_lock("vm", target_id, "owner-b")

        assert raised.value.existing["owner_id"] == "owner-a"
        assert raised.value.existing["target_id"] == target_id
        assert "path" not in raised.value.to_dict()
    finally:
        release_target_operation_lock(handle)

    second = acquire_target_operation_lock("vm", target_id, "owner-b")
    release_target_operation_lock(second)


def test_target_operation_lock_release_does_not_remove_replaced_owner_lock():
    target_id = f"node-a:{uuid.uuid4().hex}"
    first = acquire_target_operation_lock("vm", target_id, "owner-a")
    path = first.path
    path.unlink()
    replacement = acquire_target_operation_lock("vm", target_id, "owner-b")

    try:
        release_target_operation_lock(first)

        with pytest.raises(TargetOperationLockBusy) as raised:
            acquire_target_operation_lock("vm", target_id, "owner-c")
        assert raised.value.existing["owner_id"] == "owner-b"
    finally:
        release_target_operation_lock(replacement)


def test_target_operation_lock_can_be_inspected_and_released_only_by_owner():
    target_id = f"node-a:{uuid.uuid4().hex}"
    handle = acquire_target_operation_lock("vm", target_id, "owner-a")

    assert get_target_operation_lock("vm", target_id) == handle.to_dict()
    assert release_target_operation_lock_for_owner("vm", target_id, "owner-b") is False
    assert get_target_operation_lock("vm", target_id)["owner_id"] == "owner-a"
    assert release_target_operation_lock_for_owner("vm", target_id, "owner-a") is True
    assert get_target_operation_lock("vm", target_id) is None


def test_durable_target_lock_blocks_different_operation_types_for_same_vmid(monkeypatch):
    monkeypatch.setenv("GJALLAR_CLUSTER_ID", "cluster-a")
    first = acquire_target_operation_lock(
        "proxmox_vm",
        "vmid:306",
        "operation-start-306",
        operation_type="vm_start",
    )

    try:
        assert first.to_dict()["durable"]["cluster_id"] == "cluster-a"
        assert first.to_dict()["durable"]["operation_type"] == "vm_start"
        with pytest.raises(TargetOperationLockBusy) as raised:
            acquire_target_operation_lock(
                "proxmox_vm",
                "vmid:306",
                "operation-create-306",
                operation_type="vm_create",
            )
        assert raised.value.existing["operation_type"] == "vm_start"
        assert raised.value.existing["owner_id"] == "operation-start-306"
    finally:
        release_target_operation_lock(first)

    second = acquire_target_operation_lock(
        "proxmox_vm",
        "vmid:306",
        "operation-create-306",
        operation_type="vm_create",
    )
    release_target_operation_lock(second)


def test_file_acquire_error_rolls_back_durable_target_lock(monkeypatch):
    monkeypatch.setenv("GJALLAR_CLUSTER_ID", "cluster-file-error")

    with patch("app.operations.target_lock.os.open", side_effect=PermissionError("read-only runtime")):
        with pytest.raises(PermissionError):
            acquire_target_operation_lock(
                "proxmox_vm",
                "vmid:307",
                "operation-start-307",
                operation_type="vm_start",
            )

    assert get_target_operation_lock("proxmox_vm", "vmid:307") is None
