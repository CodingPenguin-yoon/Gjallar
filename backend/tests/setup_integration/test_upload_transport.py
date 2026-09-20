from io import BytesIO

import pytest

from app.setup_integration import transport
from app.setup_integration.contracts import SetupError


@pytest.fixture
def upload(monkeypatch):
    client = object.__new__(transport.ProxmoxSetupTransport)
    sent = {}
    def send(method, route, headers, body, **kwargs):
        sent.update(method=method, route=route, headers=headers, chunks=list(body))
        return 'synthetic-upload-upid'
    monkeypatch.setattr(client, '_send', send)
    payload = b'QFI\xfb' + b'x' * (150 * 1024)
    args = dict(node='node1', storage='store1', filename='gjallar-image-40000-' + 'a' * 64 + '.qcow2',
                file=BytesIO(payload), size=len(payload), sha256='b' * 64, token_id='test@pve!test', secret='synthetic', heartbeat=lambda: None)
    return client, args, sent


def test_upload_uses_bounded_stream_with_exact_length_and_checksum(upload):
    client, args, sent = upload
    assert client.upload_import(**args) == 'synthetic-upload-upid'
    assert sent['route'] == '/api2/json/nodes/node1/storage/store1/upload'
    assert sent['method'] == 'POST'
    wire = b''.join(sent['chunks'])
    assert len(wire) == int(sent['headers']['Content-Length'])
    assert max(map(len, sent['chunks'])) <= 64 * 1024
    assert b'name="content"\r\n\r\nimport\r\n' in wire
    assert b'name="checksum-algorithm"\r\n\r\nsha256\r\n' in wire
    assert b'name="checksum"\r\n\r\n' + b'b' * 64 in wire
    assert wire.count(args['file'].getvalue()) == 1
    assert b'synthetic' not in wire


@pytest.mark.parametrize('patch', [{'node': '../node'}, {'storage': 'a/b'}, {'filename': 'other.qcow2'},
    {'filename': 'gjallar-image-40000-' + 'a' * 64 + '.qcow2\r\nX: injected'}, {'size': True}, {'size': 2 * 1024 ** 3},
    {'sha256': 'bad'}, {'secret': 'abc\r\ninjected'}, {'token_id': ''}])
def test_invalid_upload_never_dispatches(upload, patch):
    client, args, sent = upload
    with pytest.raises(SetupError): client.upload_import(**{**args, **patch})
    assert not sent


@pytest.mark.parametrize('delta', [-1, 1])
def test_changed_stream_size_is_not_accepted(upload, delta):
    client, args, _ = upload
    with pytest.raises(SetupError) as caught: client.upload_import(**{**args, 'size': args['size'] + delta})
    assert caught.value.code == 'PROXMOX_UPLOAD_INCOMPLETE'


def test_upload_lease_loss_aborts_stream(upload):
    client, args, _ = upload
    def lost(): raise RuntimeError('lease lost')
    with pytest.raises(RuntimeError, match='lease lost'): client.upload_import(**{**args, 'heartbeat': lost})
