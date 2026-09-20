import hashlib
from io import BytesIO
import os
import struct
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.cloud_images import download
from app.cloud_images.catalog import ALMA_9, CATALOG, ImageError, image_by_id


def qcow():
    header = bytearray(104)
    header[:4] = b'QFI\xfb'
    struct.pack_into('>I', header, 4, 3)
    struct.pack_into('>I', header, 20, 16)
    struct.pack_into('>Q', header, 24, 10 * 1024 ** 3)
    return bytes(header) + b'synthetic-image'


@pytest.fixture
def source(monkeypatch):
    payload = qcow()
    state = {'payload': payload, 'status': 200, 'headers': {'Content-Length': str(len(payload))},
             'requests': [], 'closed': False, 'addresses': ['1.1.1.1'], 'dns': [], 'tls': []}
    image = replace(ALMA_9, image_id='synthetic-image', download_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    monkeypatch.setitem(CATALOG, image.image_id, image)
    class Response:
        @property
        def status(self): return state['status']
        def getheader(self, name, default=None): return state['headers'].get(name, default)
        def read1(self, size):
            # Partial network frames are allowed; no wait for a whole MiB.
            return state['stream'].read(min(size, 17))
    class Connection:
        def __init__(self, host, port, **kwargs):
            assert (host, port) == ('repo.almalinux.org', 443)
        def request(self, method, path, **kwargs): state['requests'].append((method, path, kwargs))
        def getresponse(self):
            state['stream'] = BytesIO(state['payload'])
            return Response()
        def close(self): state['closed'] = True
    class Sock:
        def settimeout(self, timeout): assert timeout == 15
        def close(self): state['closed'] = True
    def resolve(*args, **kwargs):
        state['dns'].append(args)
        return [(None, None, None, None, (address, 443)) for address in state['addresses']]
    def connect(address, timeout):
        assert address == ('1.1.1.1', 443) and timeout == 5
        return Sock()
    def wrap(sock, server_hostname):
        state['tls'].append(server_hostname)
        return sock
    monkeypatch.setattr(download, 'socket', SimpleNamespace(getaddrinfo=resolve, create_connection=connect, SOCK_STREAM=1))
    monkeypatch.setattr(download.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(download.ssl, 'create_default_context', lambda: SimpleNamespace(wrap_socket=wrap))
    return image.image_id, state


def test_catalog_is_exact_and_does_not_accept_arbitrary_url():
    assert image_by_id(ALMA_9.image_id) is ALMA_9
    assert 'latest' not in ALMA_9.url
    with pytest.raises(ImageError): image_by_id('https://127.0.0.1/secret')


def test_download_checks_size_hash_header_tls_and_cleans_private_file(source):
    image_id, state = source
    heartbeats = []
    with download.verified_download(image_id, heartbeat=lambda: heartbeats.append(True)) as (file, proof):
        assert os.fstat(file.fileno()).st_mode & 0o777 == 0o600
        assert file.read() == qcow()
        assert proof['virtual_size_bytes'] == 10 * 1024 ** 3
        assert state['closed'] and state['tls'] == ['repo.almalinux.org']
        assert state['requests'][0][2]['headers']['Accept-Encoding'] == 'identity'
    assert file.closed and len(heartbeats) == 2


@pytest.mark.parametrize('patch,code', [
    ({'status': 302}, 'IMAGE_DOWNLOAD_REJECTED'), ({'status': 401}, 'IMAGE_DOWNLOAD_REJECTED'),
    ({'headers': {'Content-Length': '999'}}, 'IMAGE_SIZE_MISMATCH'),
    ({'headers': {'Content-Encoding': 'gzip'}}, 'IMAGE_DOWNLOAD_REJECTED'),
    ({'payload': qcow() + b'overflow'}, 'IMAGE_SIZE_MISMATCH'),
    ({'payload': qcow()[:-1]}, 'IMAGE_INTEGRITY_FAILED'),
    ({'payload': qcow()[:-1] + b'!'}, 'IMAGE_INTEGRITY_FAILED'),
    ({'addresses': ['127.0.0.1']}, 'IMAGE_SOURCE_REJECTED'),
    ({'addresses': ['1.1.1.1', '192.168.1.1']}, 'IMAGE_SOURCE_REJECTED'),
    ({'addresses': ['::1']}, 'IMAGE_SOURCE_REJECTED'),
])
def test_rejected_download_never_yields_to_upload(source, patch, code):
    image_id, state = source
    state.update(patch)
    with pytest.raises(ImageError) as caught:
        with download.verified_download(image_id): pytest.fail('must not upload')
    assert caught.value.code == code


@pytest.mark.parametrize('offset,kind,value', [(4, '>I', 1), (8, '>Q', 100), (16, '>I', 5), (20, '>I', 8),
    (24, '>Q', 65 * 1024 ** 3), (32, '>I', 1), (60, '>I', 1), (72, '>Q', 4)])
def test_external_backing_encryption_snapshot_and_oversize_are_rejected(offset, kind, value):
    header = bytearray(qcow())
    struct.pack_into(kind, header, offset, value)
    with pytest.raises(ImageError): download.qcow2_virtual_size(header)


def test_caller_failure_is_not_misclassified_and_file_is_removed(source):
    image_id, _ = source
    with pytest.raises(OSError, match='synthetic upload error'):
        with download.verified_download(image_id) as (file, _):
            raise OSError('synthetic upload error')
    assert file.closed


def test_lease_failure_stops_before_upload_and_cleans_file(source):
    image_id, state = source
    def heartbeat(): raise RuntimeError('lease lost')
    with pytest.raises(RuntimeError, match='lease lost'):
        with download.verified_download(image_id, heartbeat=heartbeat): pytest.fail('must not upload')
    assert state['closed']


def test_concurrency_is_bounded_and_released_after_error(source):
    image_id, _ = source
    with download.verified_download(image_id), download.verified_download(image_id):
        with pytest.raises(ImageError) as caught:
            with download.verified_download(image_id): pytest.fail('limit')
        assert caught.value.code == 'IMAGE_DOWNLOAD_BUSY'
    with download.verified_download(image_id): pass
