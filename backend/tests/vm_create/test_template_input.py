"""Template input does not require the DB profile catalog."""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.proxmox.inventory import FakeProxmoxInventoryAdapter
from app.vm_create import application


def _input():
    adapter = FakeProxmoxInventoryAdapter()
    template = adapter.list_templates()[0]
    return adapter, {
        "creation_mode": "template", "job_id": "job-template-input",
        "template_node_id": template.node_id, "template_vmid": template.vmid, "template_id": template.template_id,
        "target_node_id": "yoonmanserver2", "bridge_id": "vmbr0", "ip_mode": "dhcp",
        "access": {"cloud_init_user": "operator"},
    }


def test_template_review_approval_and_fresh_validation_do_not_read_profiles(monkeypatch):
    adapter, payload = _input()
    profiles = Mock(side_effect=AssertionError("DB profile dependency"))
    monkeypatch.setattr(application, "get_active_create_vm_profiles_by_id", profiles)
    draft = asyncio.run(application.create_draft(payload, actor=None, inventory_adapter=adapter))
    assert draft.data["profile_id"] == ""
    preflight = asyncio.run(application.preflight_draft(draft.data["draft_id"], payload, actor=None, inventory_adapter=adapter))
    assert preflight.data["risk_level"] != "red"
    result = asyncio.run(application.plan_draft(draft.data["draft_id"], payload, actor=None, inventory_adapter=adapter))
    assert result.data["hardware"]["disk_gb"] == adapter.list_templates()[0].disk_gb
    assert result.data["profile_hardware_limits"] == {}
    review = result.data["review_confirm"]
    payload.update({"plan_artifact_id": review["plan_artifact_id"], "review_summary_checksum": review["review_summary_checksum"], "yellow_risk_acknowledged": True})
    approval = asyncio.run(application.approve_draft(draft.data["draft_id"], payload, actor=None, inventory_adapter=adapter))
    assert approval.data["can_execute"] is True
    plan = application.build_preview_plan(draft.data["draft_id"], payload, inventory_adapter=adapter)
    application._validate_fresh_create_state(plan, payload, adapter)
    profiles.assert_not_called()


@pytest.mark.parametrize("patch,code", [
    ({"profile_id": "general-vm"}, "AMBIGUOUS_CREATE_MODE"),
    ({"creation_mode": "unknown"}, "INVALID_CREATE_MODE"),
    ({"creation_mode": []}, "INVALID_CREATE_MODE"),
    ({"template_vmid": 1}, "CREATE_TEMPLATE_UNAVAILABLE"),
    ({"template_id": "different"}, "CREATE_TEMPLATE_ID_MISMATCH"),
    ({"hardware_overrides": {"cpu": 1.5}}, "INVALID_CREATE_HARDWARE"),
    ({"hardware_overrides": {"cpu": True}}, "INVALID_CREATE_HARDWARE"),
    ({"hardware_overrides": {"memory_mb": 0}}, "INVALID_CREATE_HARDWARE"),
])
def test_invalid_template_input_is_rejected(patch, code):
    adapter, payload = _input()
    with pytest.raises(application.VmCreateApplicationError) as error:
        application.build_preview_plan("draft-template-input", {**payload, **patch}, inventory_adapter=adapter)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == code


@pytest.mark.parametrize("patch,risk", [
    ({"hardware_overrides": {"cpu": 999999}}, "target_cpu_capacity"),
    ({"hardware_overrides": {"memory_mb": 999999999}}, "target_memory_mb_capacity"),
    ({"hardware_overrides": {"disk_gb": 1}}, "template_disk_larger_than_requested"),
    ({"access": {"cloud_init_user": ""}}, "cloud_init_user_missing"),
])
def test_template_input_keeps_resource_and_access_guards(patch, risk):
    adapter, payload = _input()
    plan = application.build_preview_plan("draft-template-input", {**payload, **patch}, inventory_adapter=adapter)
    assert plan.risk_summary["level"] == "red"
    assert risk in {item["code"] for item in plan.risk_summary["red"]}


def test_template_family_is_not_restricted_to_ubuntu():
    adapter, payload = _input()
    adapter._templates = tuple(replace(template, family="debian") for template in adapter._templates)
    plan = application.build_preview_plan("draft-template-input", payload, inventory_adapter=adapter)
    assert plan.risk_summary["level"] != "red"
    assert plan.selected_template["family"] == "debian"


@pytest.mark.parametrize("linkage", ["valid", "missing", "foreign", "corrupt_history", "reused_vmid"])
def test_template_execute_persists_result_without_profile_catalog(monkeypatch, linkage):
    from app.db.vm_runtime import get_vm_instance_record, get_vm_create_request_record
    from app.jobs.artifacts import write_json_artifact

    adapter, payload = _input()
    monkeypatch.setattr(application, "get_active_create_vm_profiles_by_id", Mock(side_effect=AssertionError("profile lookup")))
    plan = application.build_preview_plan("draft-template-input", payload, inventory_adapter=adapter)
    payload.update({
        "plan_artifact_id": plan.review_confirm["plan_artifact_id"],
        "review_summary_checksum": plan.review_confirm["review_summary_checksum"],
        "yellow_risk_acknowledged": True, "proxmox_mutation_acknowledged": True,
    })

    def simulated_create(plan, *, run_dir, client, checkpoint, heartbeat, progress=None):
        observed = {"vmid": plan.vmid, "target_node_id": plan.target_node_id, "exists": True,
                    "status": "stopped", "fingerprint": {"hash": "sha256:" + "1" * 64}}
        artifact = write_json_artifact(run_dir=run_dir, job_id=plan.job_id, artifact_type="observed_after",
                                       filename="observed_after.json", payload=observed)
        return {"job_id": plan.job_id, "manifest_id": plan.manifest_id, "vmid": plan.vmid,
                "target_node_id": plan.target_node_id, "success": True, "status": "completed",
                "message": "simulated verified stopped VM", "observed_after": observed,
                "observed_after_artifact": artifact.to_dict(), "artifacts": [artifact.to_dict()],
                "side_effects": ["proxmox_clone_invoked", "proxmox_post_check_observed"]}

    runner = Mock(side_effect=simulated_create)
    monkeypatch.setattr(application, "run_proxmox_create", runner)
    result = asyncio.run(application.execute_proxmox_create(
        plan.draft_id, payload, actor=None, inventory_adapter=adapter, mutation_client_factory=lambda: object(),
    ))
    assert result.data["operation"]["status"] == "succeeded"
    from app.db.session import session_scope
    from app.db.models import VmInstanceRecord
    with session_scope() as session:
        assert session.get(VmInstanceRecord, f"{plan.target_node_id}:{plan.vmid}") is None
    assert get_vm_instance_record(plan.target_node_id, plan.vmid, create_job_id=plan.job_id) is None
    assert get_vm_create_request_record(plan.job_id)["status"] == "completed"
    if linkage == "corrupt_history":
        from app.operations.core.infrastructure.models import OperationRecord
        with session_scope() as session:
            op = session.get(OperationRecord, plan.job_id)
            op.details = {**op.details, "workload": {**op.details["workload"], "vmid": plan.vmid + 1}}
        with pytest.raises(application.VmCreateApplicationError) as error:
            asyncio.run(application.execute_proxmox_create(
                plan.draft_id, payload, actor=None, inventory_adapter=adapter, mutation_client_factory=lambda: object(),
            ))
        assert error.value.detail["code"] == "PROXMOX_CREATE_RECONCILIATION_REQUIRED"
        assert runner.call_count == 1
        return
    if linkage == "foreign":
        with session_scope() as session:
            session.add(VmInstanceRecord(vm_instance_id=f"{plan.target_node_id}:{plan.vmid}",
                node_id=plan.target_node_id, vmid=plan.vmid, name="foreign-vm", status="running",
                profile_id="", create_job_id="another-job", created_at="now", updated_at="now"))
    if linkage == "reused_vmid":
        second_payload = {**payload, "job_id": "job-template-second"}
        second_plan = application.build_preview_plan("draft-template-second", second_payload, inventory_adapter=adapter)
        assert second_plan.vmid == plan.vmid
        second_payload.update({
            "plan_artifact_id": second_plan.review_confirm["plan_artifact_id"],
            "review_summary_checksum": second_plan.review_confirm["review_summary_checksum"],
        })
        second = asyncio.run(application.execute_proxmox_create(
            second_plan.draft_id, second_payload, actor=None, inventory_adapter=adapter,
            mutation_client_factory=lambda: object(),
        ))
        assert second.data["operation"]["status"] == "succeeded"
        assert second.data["operation"]["operation_id"] != result.data["operation"]["operation_id"]
    replay = asyncio.run(application.execute_proxmox_create(
        plan.draft_id, payload, actor=None, inventory_adapter=adapter, mutation_client_factory=lambda: object(),
    ))
    assert replay.data["idempotent_replay"] is True
    assert replay.data["vm_instance"] == result.data["vm_instance"]
    if linkage == "foreign":
        row = get_vm_instance_record(plan.target_node_id, plan.vmid, create_job_id="another-job")
        assert row["name"] == "foreign-vm"
    assert runner.call_count == (2 if linkage == "reused_vmid" else 1)


def test_template_hardware_aliases_preserve_requested_values():
    adapter, payload = _input()
    payload["hardware"] = {"cpu": 3, "memoryMb": 6144, "diskGb": 80}
    draft = application.build_draft_from_payload("draft-alias", payload, inventory_adapter=adapter)
    assert draft.hardware.to_dict() == {"cpu": 3, "memory_mb": 6144, "disk_gb": 80}


@pytest.mark.parametrize('value', [True, False, 99, 1000000000, 100.5, '100.0', '', 'abc'])
def test_explicit_vmid_rejects_invalid_values(value):
    adapter, payload = _input()
    with pytest.raises(application.VmCreateApplicationError) as error:
        application.build_draft_from_payload('draft-vmid', {**payload, 'vmid': value}, inventory_adapter=adapter)
    assert error.value.detail['code'] == 'INVALID_VM_ID'


def test_explicit_vmid_and_name_do_not_use_recommendation(monkeypatch):
    adapter, payload = _input()
    monkeypatch.setattr(adapter, 'suggest_next_vmid', Mock(side_effect=AssertionError('unexpected recommendation')))
    plan = application.build_preview_plan('draft-vmid', {**payload, 'vmid': '4321', 'vm_name': 'app-server-01'}, inventory_adapter=adapter)
    assert plan.vmid == 4321
    assert plan.vm_name == 'app-server-01'


def test_explicit_vmid_collision_is_a_red_preflight():
    adapter, payload = _input()
    vmid = adapter.list_templates()[0].vmid
    plan = application.build_preview_plan('draft-vmid', {**payload, 'vmid': vmid}, inventory_adapter=adapter)
    assert plan.risk_summary['level'] == 'red'
    assert 'vmid_collision' in {risk['code'] for risk in plan.risk_summary['red']}


@pytest.mark.parametrize('name', ['', '-bad', 'bad-', 'a b', 'a' * 64, 123])
def test_explicit_vm_name_is_validated(name):
    adapter, payload = _input()
    with pytest.raises(application.VmCreateApplicationError) as error:
        application.build_draft_from_payload('draft-name', {**payload, 'vm_name': name}, inventory_adapter=adapter)
    assert error.value.detail['code'] == 'INVALID_VM_NAME'
