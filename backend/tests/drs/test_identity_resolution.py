from sqlalchemy import func, select


def _vm(
    *,
    vmid=101,
    name="app-01",
    node_id="node-a",
    smbios1="uuid=11111111-2222-3333-4444-555555555555",
    vmgenid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    mac_addresses=("aa:bb:cc:dd:ee:ff",),
    disk_volume_ids=("shared-nfs:vm-101-disk-0",),
):
    from app.proxmox.models import DiskInventory, VmInventory

    return VmInventory(
        vmid=vmid,
        name=name,
        node_id=node_id,
        status="running",
        template=False,
        cpu=2,
        memory_mb=8192,
        disk_gb=40,
        smbios1=smbios1,
        vmgenid=vmgenid,
        mac_addresses=mac_addresses,
        storage_id="shared-nfs" if disk_volume_ids else "unknown",
        disks=tuple(
            DiskInventory(
                device=f"scsi{index}",
                bus="scsi",
                index=index,
                size_gb=40,
                storage_id=volume_id.split(":", 1)[0],
                volume_id=volume_id,
                volume=volume_id.split(":", 1)[-1],
                boot=index == 0,
            )
            for index, volume_id in enumerate(disk_volume_ids)
        ),
    )


def test_first_high_confidence_observation_creates_identity_and_observation():
    from app.db.models import VmIdentityObservationRecord, VmIdentityRecord
    from app.db.session import session_scope
    from app.drs.identity import resolve_vm_identity

    with session_scope() as session:
        result = resolve_vm_identity(
            session,
            _vm(),
            cluster_id="cluster-a",
            observed_at="2026-05-28T00:00:00+00:00",
            source="unit_test",
        )
        session.flush()
        identity_count = session.scalar(select(func.count()).select_from(VmIdentityRecord))
        observation_count = session.scalar(select(func.count()).select_from(VmIdentityObservationRecord))

    assert result.match_confidence == "high"
    assert result.vm_identity_id is not None
    assert result.stable_fingerprint.startswith("sha256:")
    assert identity_count == 1
    assert observation_count == 1


def test_repeated_high_confidence_observation_matches_same_identity_after_node_change():
    from app.db.models import VmIdentityObservationRecord
    from app.db.session import session_scope
    from app.drs.identity import resolve_vm_identity

    with session_scope() as session:
        first = resolve_vm_identity(session, _vm(node_id="node-a"), cluster_id="cluster-a")
    with session_scope() as session:
        second = resolve_vm_identity(session, _vm(node_id="node-b"), cluster_id="cluster-a")
        observation_count = session.scalar(select(func.count()).select_from(VmIdentityObservationRecord))

    assert first.match_confidence == "high"
    assert second.match_confidence == "high"
    assert second.vm_identity_id == first.vm_identity_id
    assert observation_count == 2


def test_same_cluster_vmid_different_fingerprint_on_different_node_is_conflict():
    from app.db.models import VmIdentityObservationRecord, VmIdentityRecord
    from app.db.session import session_scope
    from app.drs.identity import resolve_vm_identity

    with session_scope() as session:
        first = resolve_vm_identity(
            session,
            _vm(node_id="node-a"),
            cluster_id="cluster-a",
            observed_at="2026-05-28T00:00:00+00:00",
        )
    with session_scope() as session:
        second = resolve_vm_identity(
            session,
            _vm(
                node_id="node-b",
                smbios1="uuid=99999999-2222-3333-4444-555555555555",
                vmgenid="99999999-bbbb-cccc-dddd-eeeeeeeeeeee",
                mac_addresses=("aa:bb:cc:dd:ee:99",),
                disk_volume_ids=("shared-nfs:vm-101-disk-9",),
            ),
            cluster_id="cluster-a",
            observed_at="2026-05-28T00:01:00+00:00",
        )
        identity_count = session.scalar(select(func.count()).select_from(VmIdentityRecord))
        observation_count = session.scalar(select(func.count()).select_from(VmIdentityObservationRecord))

    assert first.match_confidence == "high"
    assert second.match_confidence == "low"
    assert second.conflict_signal is True
    assert second.vm_identity_id is None
    assert second.match_reason == "locator_conflicts_with_existing_identity"
    assert identity_count == 1
    assert observation_count == 1


def test_supporting_only_identity_is_not_high_confidence():
    from app.db.models import VmIdentityRecord
    from app.db.session import session_scope
    from app.drs.identity import resolve_vm_identity

    with session_scope() as session:
        result = resolve_vm_identity(
            session,
            _vm(smbios1="", vmgenid="", disk_volume_ids=(), mac_addresses=("aa:bb:cc:dd:ee:ff",)),
            cluster_id="cluster-a",
        )
        identity_count = session.scalar(select(func.count()).select_from(VmIdentityRecord))

    assert result.match_confidence == "medium"
    assert result.vm_identity_id is None
    assert result.to_evidence()["blocking"] is True
    assert identity_count == 0


def test_duplicate_current_stable_fingerprint_is_low_confidence_conflict():
    from app.drs.identity import resolve_inventory_identities

    first = _vm(vmid=101, name="app-01")
    duplicate = _vm(vmid=102, name="app-02")
    result = resolve_inventory_identities([first, duplicate], cluster_id="cluster-a")

    confidences = {item.match_confidence for item in result.values()}
    assert confidences == {"low"}
    assert all(item.conflict_signal is True for item in result.values())
