import pytest

from app.operations.vm_disk.domain import (
    GIB, DiskError, DiskRequest, check_expected, disk_identity, observed_disk, verified_task_reference,
)


CONFIG = {"name": "test-vm", "digest": "a" * 40, "scsi0": "store1:40000/vm-40000-disk-0.qcow2,size=20G"}
STORAGES = [{"storage": "store1", "type": "nfs", "active": 1, "enabled": 1}]
VOLUME = {"size": 20 * GIB, "format": "qcow2", "path": "/private/path/not-for-operation"}


def test_exact_volume_bytes_and_absolute_growth():
    state = observed_disk(disk_identity(CONFIG, {"status": "stopped"}, [], vmid=40000), STORAGES, VOLUME)
    assert state["size_bytes"] == 20 * GIB
    assert "path" not in state
    request = DiskRequest(idempotency_key="disk-review-1", expected_digest="a" * 40, expected_name="test-vm",
        expected_volume=state["volume_id"], expected_size_bytes=20 * GIB, size_gib=24)
    check_expected(state, request)
    for size in (10, 20):
        with pytest.raises(DiskError, match="축소"):
            check_expected(state, request.model_copy(update={"size_gib": size}))
    with pytest.raises(DiskError, match="변경"):
        check_expected(state, request.model_copy(update={"expected_volume": "different"}))


@pytest.mark.parametrize("disk", [
    "store1:40001/vm-40001-disk-0.qcow2,size=20G", "store1:40000/base-40000-disk-0.qcow2,size=20G",
    "store1:vm-40000-disk-0,size=20G", "store1:40000/vm-40000-disk-0.qcow2,size=20G,shared=1",
    "store1:40000/vm-40000-disk-0.raw,size=20G,media=cdrom", "store1:40000/vm-40000-disk-0.raw,size=20G,ro=1",
    "store1:40000/vm-40000-disk-0.raw,size=20G,size=30G", "store1:40000/vm-40000-disk-0.raw",
])
def test_unsupported_or_unowned_disks_are_rejected(disk):
    with pytest.raises(DiskError):
        disk_identity({**CONFIG, "scsi0": disk}, {"status": "stopped"}, [], vmid=40000)


@pytest.mark.parametrize("config,status,pending", [
    (CONFIG, "running", []), ({**CONFIG, "template": 1}, "stopped", []),
    ({**CONFIG, "lock": "backup"}, "stopped", []), (CONFIG, "stopped", [{"key": "scsi0", "pending": "x"}]),
    ({**CONFIG, "digest": "invalid"}, "stopped", []),
])
def test_vm_state_must_be_observable(config, status, pending):
    with pytest.raises(DiskError):
        disk_identity(config, {"status": status}, pending, vmid=40000)


@pytest.mark.parametrize("storages,volume", [
    ([], VOLUME), ([{**STORAGES[0], "type": "lvmthin"}], VOLUME),
    ([{**STORAGES[0], "active": 0}], VOLUME), (STORAGES, {**VOLUME, "size": 21 * GIB}),
    (STORAGES, {"approximate-size": 20 * GIB, "format": "qcow2"}),
    (STORAGES, {**VOLUME, "format": "raw"}),
])
def test_config_size_never_replaces_real_volume_evidence(storages, volume):
    with pytest.raises(DiskError):
        observed_disk(disk_identity(CONFIG, {"status": "stopped"}, [], vmid=40000), storages, volume)


def test_task_locator_must_match_action_and_exact_target():
    upid = "UPID:node1:00000001:00000002:00000003:resize:40000:test@pve!gjallar:"
    assert verified_task_reference(upid, node_id="node1", vmid=40000) == upid
    for value in (upid.replace("node1", "node2"), upid.replace("resize", "qmstart"),
                  upid.replace("40000", "40001"), "secret\n" + upid, None):
        with pytest.raises(DiskError):
            verified_task_reference(value, node_id="node1", vmid=40000)
