import pytest
from pydantic import ValidationError

from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.planning import ROLE_PRIVILEGES, acl_plan, verify_token
from app.setup_integration.runtime import ManagedRequests, managed_mutation_client


SCOPE = {"nodes": ["node1"], "vmids": [101], "template_vmids": [9000],
         "create_vmids": [40000], "storages": ["store1"], "bridges": ["vmbr0"]}
CONFIG = {"cores": 2, "memory": 2048, "agent": "enabled=1", "onboot": 0,
          "net0": "virtio,bridge=vmbr0", "ciuser": "test", "ipconfig0": "ip=dhcp"}
CLONE = {"newid": 40000, "name": "test-vm", "target": "node1", "storage": "store1", "full": 1}


@pytest.fixture
def managed_create(monkeypatch):
    calls = []

    class Transport:
        def __init__(self, *args):
            pass

        def request(self, method, path, *, data=None, **kwargs):
            calls.append((method, path, data))
            if path.endswith("/clone") or path.endswith("/status/start"):
                return "UPID:node1:0001:qmclone"
            if path.endswith("/agent/exec"):
                return {"pid": 42}
            if path.endswith("/agent/exec-status"):
                return {"exited": True, "exitcode": 0}
            if path.endswith("/qemu"):
                return [{"vmid": value} for value in (101, 9000, 40000, 40001)]
            return None

    monkeypatch.setattr("app.setup_integration.transport.ProxmoxSetupTransport", Transport)
    selection = {"secret": "synthetic", "configuration": {
        "endpoint": "https://pve.example.test", "ca_pem": "", "token_id": "test@pve!test",
        "features": ["read", "create"], "scope": SCOPE,
    }}
    return ManagedRequests(selection), managed_mutation_client(selection), calls


def test_existing_create_client_payloads_are_allowed(managed_create):
    requests, client, calls = managed_create
    client.clone_vm(template_node="node1", template_vmid=9000, **{key: value for key, value in CLONE.items() if key != "full"})
    client.set_vm_config(node="node1", vmid=40000, config=CONFIG)
    client.resize_vm_disk(node="node1", vmid=40000, disk="scsi0", size=64)
    client.start_vm(node="node1", vmid=40000)
    assert client.exec_guest_command(node="node1", vmid=40000, command=("cloud-init", "status", "--wait")) == 42
    assert client.get_guest_exec_status(node="node1", vmid=40000, pid=42)["exitcode"] == 0
    assert calls[-1] == ("GET", "/nodes/node1/qemu/40000/agent/exec-status", {"pid": "42"})
    assert {row["vmid"] for row in requests.get("/nodes/node1/qemu")} == {101, 9000, 40000}


@pytest.mark.parametrize("method,path,data", [
    ("POST", "/nodes/node1/qemu/101/clone", CLONE),
    ("POST", "/nodes/other/qemu/9000/clone", CLONE),
    *[("POST", "/nodes/node1/qemu/9000/clone", {**CLONE, key: value})
      for key, value in (("newid", 40001), ("target", "other"), ("storage", "other"), ("full", 0), ("pool", "other"))],
    ("PUT", "/nodes/node1/qemu/101/config", CONFIG),
    *[("PUT", "/nodes/node1/qemu/40000/config", {**CONFIG, key: value})
      for key, value in (("net0", "virtio,bridge=other"), ("net0", "virtio,bridge=vmbr0,tag=42"),
                         ("skiplock", 1), ("delete", "scsi0"), ("args", "-evil"), ("onboot", 1))],
    ("PUT", "/nodes/node1/qemu/40000/resize", {"disk": "scsi0", "size": "-10G"}),
    ("DELETE", "/nodes/node1/qemu/40000", None),
    ("POST", "/nodes/node1/qemu/40000/agent/exec", {"command": "sh"}),
    ("POST", "/nodes/node1/qemu/40000/agent/exec", [("command", "cloud-init"), ("command", "clean")]),
    ("GET", "/nodes/node1/qemu/40001/agent/exec-status?pid=42", None),
    ("GET", "/nodes/node1/qemu/40000/agent/exec-status?pid=42&extra=1", None),
])
def test_creation_cannot_escape_reviewed_scope(managed_create, method, path, data):
    requests, _, calls = managed_create
    with pytest.raises(SetupError):
        requests.request(method, path, data=data)
    assert not calls


def test_creation_plan_requires_explicit_scopes_and_preserves_read_roles():
    values = dict(endpoint="https://pve.example.test", owner="test@pve", scope=SCOPE,
                  features=["read", "create"], expires_at=2000000000)
    intent = RegistrationIntent(**values)
    acls = acl_plan(intent)
    assert {row["role"] for row in acls if row["path"] == "/vms/101"} == {"GjallarVmReadV1"}
    assert {row["role"] for row in acls if row["path"] == "/vms/9000"} == {"GjallarTemplateCloneV1"}
    assert {row["role"] for row in acls if row["path"] == "/vms/40000"} == {"GjallarVmCreateV1"}
    assert "VM.Allocate" not in ROLE_PRIVILEGES["GjallarVmComputeV1"]
    for scope in ({**SCOPE, "create_vmids": []}, {**SCOPE, "create_vmids": [101]}, {**SCOPE, "bridges": []}):
        with pytest.raises(ValidationError):
            RegistrationIntent(**{**values, "scope": scope})


def test_verify_accepts_future_target_but_requires_real_template():
    intent = RegistrationIntent(endpoint="https://pve.example.test", owner="test@pve", scope=SCOPE,
                                features=["read", "create"], expires_at=2000000000)
    template = True

    def request(method, path, *, data=None):
        if path == "/access/permissions":
            privileges = {priv for row in acl_plan(intent) if row["path"] == data["path"] for priv in ROLE_PRIVILEGES[row["role"]]}
            return {data["path"]: dict.fromkeys(privileges, 1)}
        return {"/nodes": [{"node": "node1"}], "/nodes/node1/qemu": [{"vmid": 101}, {"vmid": 9000}],
                "/nodes/node1/qemu/101/config": {}, "/nodes/node1/qemu/9000/config": {"template": int(template)},
                "/nodes/node1/storage": [{"storage": "store1"}], "/nodes/node1/network": [{"iface": "vmbr0"}]}[path]

    assert verify_token(intent, request)["vmids"] == [101, 9000]
    template = False
    with pytest.raises(SetupError, match="템플릿"):
        verify_token(intent, request)
