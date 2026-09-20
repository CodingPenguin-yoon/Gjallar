"""PVE accepts DELETE options in the URL, and rejects a nonempty DELETE body."""
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest

from app.setup_integration.transport import ProxmoxSetupTransport
from app.proxmox.client import ProxmoxMutationClient


@pytest.mark.parametrize('method', ['GET', 'DELETE', 'POST', 'PUT'])
@pytest.mark.parametrize('data', [None, {}, {'purge': 0, 'destroy-unreferenced-disks': 0}])
def test_managed_request_encoding_preserves_zero_options_without_delete_body(monkeypatch, method, data):
    client = object.__new__(ProxmoxSetupTransport)
    send = Mock(return_value='synthetic-result')
    monkeypatch.setattr(client, '_send', send)
    assert client.request(method, '/nodes/node1/qemu/40000', data=data,
                          token_id='synthetic@pve!test', secret='synthetic-secret') == 'synthetic-result'
    sent_method, route, headers, body = send.call_args.args
    assert sent_method == method
    expected = {key: [str(value)] for key, value in (data or {}).items()}
    if method in {'GET', 'DELETE'}:
        assert body is None
        assert 'Content-Type' not in headers
        assert parse_qs(urlsplit(route).query) == expected
    else:
        assert not urlsplit(route).query
        assert parse_qs(body.decode()) == expected
    assert 'synthetic-secret' not in route


def test_legacy_delete_options_use_query_and_keep_zero_values(monkeypatch):
    response = Mock()
    response.json.return_value = {'data': 'synthetic-task'}
    send = Mock(return_value=response)
    monkeypatch.setattr('app.proxmox.client.requests.request', send)
    client = ProxmoxMutationClient(api_url='https://pve.example.test:8006/api2/json',
                           token_id='synthetic@pve!test', token_secret='synthetic-secret')
    assert client.delete_vm_reviewed(node='node1', vmid=40000) == 'synthetic-task'
    assert send.call_args.kwargs['params'] == {'purge': 0, 'destroy-unreferenced-disks': 0}
    assert send.call_args.kwargs.get('data') is None
