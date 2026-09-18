"""Use the independent client against the real FastAPI cookie contracts, no network."""
from pathlib import Path
import sys

import httpx
import pytest
from fastapi.testclient import TestClient


def test_client_real_cookie_contract_and_revoke(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "client" / "src"))
    from gjallar_client.api import Api
    from gjallar_client.application import Application
    from gjallar_client.connections import Connections
    from gjallar_client.sessions import MemoryStore
    from gjallar_client.errors import ClientError
    from app.auth.users import create_user, disable_user
    from app.main import app

    monkeypatch.setenv("GJALLAR_PASSWORD_HASH_ITERATIONS", "1200")
    create_user(username="reader", password="test-password", role="viewer")
    server = TestClient(app)
    def transport(request):
        server.cookies.clear()
        return server.request(request.method, request.url.path, headers=dict(request.headers), content=request.content)
    connections = Connections(tmp_path / "client-config")
    connections.add("local", "http://127.0.0.1:8000")
    client = Application(connections, MemoryStore(), lambda p: Api(p, httpx.MockTransport(transport)))
    assert client.login("reader", "test-password", "local")["user"]["role"] == "viewer"
    assert client.status()["user"]["username"] == "reader"
    for resource in ("nodes", "vms", "templates", "connection"):
        assert client.read(resource)["ok"]
    disable_user(username="reader")
    with pytest.raises(ClientError) as error:
        client.status()
    assert error.value.code == "SESSION_EXPIRED"
    server.close()


def test_cli_create_review_execute_and_operation_query_real_api(monkeypatch, tmp_path):
    import json
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'client' / 'src'))
    from gjallar_client.api import Api
    from gjallar_client.application import Application
    from gjallar_client.connections import Connections
    from gjallar_client.sessions import MemoryStore
    from gjallar_client import workflows
    from app.auth.users import create_user
    from app.main import app
    from app.proxmox.inventory import FakeProxmoxInventoryAdapter
    from app.vm_create import application as create_application
    from app.api.v1 import vm_create_compat
    from app.jobs.artifacts import write_json_artifact

    monkeypatch.setenv('GJALLAR_PASSWORD_HASH_ITERATIONS', '1200')
    create_user(username='operator-cli', password='test-password', role='operator')
    adapter = FakeProxmoxInventoryAdapter()
    template = adapter.list_templates()[0]
    spec = {'creation_mode': 'template', 'vmid': 102, 'vm_name': 'cli-test',
            'template_node_id': template.node_id, 'template_vmid': template.vmid,
            'target_node_id': 'yoonmanserver2', 'storage_id': 'local-lvm', 'bridge_id': 'vmbr0',
            'ip_mode': 'dhcp', 'power_policy': 'stopped', 'access': {'cloud_init_user': 'operator'}}
    spec_file = tmp_path / 'spec.json'
    spec_file.write_text(json.dumps(spec))
    review_file = tmp_path / 'review.json'
    calls = []

    def simulated_create(plan, *, run_dir, client, checkpoint, heartbeat, progress=None):
        calls.append(plan.job_id)
        observed = {'vmid': plan.vmid, 'target_node_id': plan.target_node_id, 'exists': True,
                    'status': 'stopped', 'fingerprint': {'hash': 'sha256:' + '1' * 64}}
        artifact = write_json_artifact(run_dir=run_dir, job_id=plan.job_id, artifact_type='observed_after',
                                       filename='observed_after.json', payload=observed)
        return {'job_id': plan.job_id, 'manifest_id': plan.manifest_id, 'vmid': plan.vmid,
                'target_node_id': plan.target_node_id, 'success': True, 'status': 'completed',
                'message': 'simulated verified VM', 'observed_after': observed,
                'observed_after_artifact': artifact.to_dict(), 'artifacts': [artifact.to_dict()],
                'side_effects': ['proxmox_clone_invoked', 'proxmox_post_check_observed']}

    monkeypatch.setattr(create_application, 'run_proxmox_create', simulated_create)
    monkeypatch.setattr(vm_create_compat, '_mutation_client_factory', lambda: object())
    with TestClient(app) as server:
        def transport(request):
            server.cookies.clear()
            return server.request(request.method, request.url.raw_path.decode(), headers=dict(request.headers), content=request.content)
        config = Connections(tmp_path / 'client-config')
        config.add('local', 'http://127.0.0.1:8000')
        client = Application(config, MemoryStore(), lambda p: Api(p, httpx.MockTransport(transport)))
        client.login('operator-cli', 'test-password', 'local')
        result = workflows.create_plan(client, spec_file, 'cli-create-1', review_file)
        assert result['exit_code'] == 0, result
        assert calls == []
        result = workflows.create_execute(client, review_file, True, lambda _: None)
        assert result['exit_code'] == 0, result
        assert calls == ['cli-create-1']
        observed = workflows.operations(client, operation_id='cli-create-1')
        assert observed['data']['operation']['status'] == 'succeeded'
        listed = workflows.operations(client, vmid=102)
        assert [row['operation_id'] for row in listed['data']] == ['cli-create-1']
