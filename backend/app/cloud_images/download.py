"""Bounded, DNS-pinned download; no proxies, redirects, image execution or mounting."""
from contextlib import contextmanager
import hashlib
import http.client
import ipaddress
import socket
import ssl
import struct
import tempfile
import threading
import time
from urllib.parse import urlsplit

from app.cloud_images.catalog import ImageError, image_by_id

MAX_FILE_BYTES = 1024 ** 3
MAX_VIRTUAL_BYTES = 64 * 1024 ** 3
DOWNLOAD_SECONDS = 600
_download_slots = threading.BoundedSemaphore(2)


def qcow2_virtual_size(header):
    if len(header) < 104 or header[:4] != b'QFI\xfb':
        raise ImageError('IMAGE_FORMAT_REJECTED', 'qcow2 header를 확인할 수 없습니다.', 422)
    version = struct.unpack_from('>I', header, 4)[0]
    backing_offset = struct.unpack_from('>Q', header, 8)[0]
    backing_size, cluster_bits = struct.unpack_from('>II', header, 16)
    size = struct.unpack_from('>Q', header, 24)[0]
    crypt_method = struct.unpack_from('>I', header, 32)[0]
    snapshots = struct.unpack_from('>I', header, 60)[0]
    incompatible = struct.unpack_from('>Q', header, 72)[0] if version == 3 else 0
    if (version not in {2, 3} or backing_offset or backing_size or crypt_method or snapshots or incompatible
            or not 9 <= cluster_bits <= 21 or not 0 < size <= MAX_VIRTUAL_BYTES):
        raise ImageError('IMAGE_FORMAT_REJECTED', '독립·미암호화 qcow2와 64 GiB 이하 가상 크기만 지원합니다.', 422)
    return size


def _download_into(image, downloaded, heartbeat):
    connection = None
    try:
        parsed = urlsplit(image.url)
        if (parsed.scheme != 'https' or parsed.hostname != 'repo.almalinux.org' or parsed.port is not None
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ImageError('IMAGE_SOURCE_REJECTED', '검토된 공식 HTTPS 출처만 사용할 수 있습니다.', 422)
        addresses = {row[4][0] for row in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ImageError('IMAGE_SOURCE_REJECTED', '공식 이미지 주소의 공개 네트워크 범위를 확인할 수 없습니다.', 503)
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(parsed.hostname, 443, context=context, timeout=15)
        plain = socket.create_connection((sorted(addresses)[0], 443), timeout=5)
        try:
            connection.sock = context.wrap_socket(plain, server_hostname=parsed.hostname)
        except BaseException:
            plain.close()
            raise
        connection.sock.settimeout(15)
        deadline = time.monotonic() + DOWNLOAD_SECONDS
        connection.request('GET', parsed.path, headers={'Accept-Encoding': 'identity', 'Accept': 'application/octet-stream'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
            raise ImageError('IMAGE_DOWNLOAD_REJECTED', '공식 이미지 다운로드 응답을 확인할 수 없습니다. redirect/압축을 허용하지 않습니다.', 503)
        length = response.getheader('Content-Length')
        if length is not None and length != str(image.download_bytes):
            raise ImageError('IMAGE_SIZE_MISMATCH', '공식 이미지의 검토된 크기와 응답 크기가 다릅니다.', 503)
        digest, received, header = hashlib.sha256(), 0, bytearray()
        heartbeat()
        next_heartbeat = time.monotonic() + 10
        while True:
            now = time.monotonic()
            if now > deadline:
                raise ImageError('IMAGE_DOWNLOAD_TIMEOUT', '이미지 다운로드 제한 시간을 초과했습니다.', 503)
            if now >= next_heartbeat:
                heartbeat()
                next_heartbeat = now + 10
            chunk = response.read1(min(64 * 1024, image.download_bytes - received + 1))
            if not chunk:
                break
            received += len(chunk)
            if received > image.download_bytes:
                raise ImageError('IMAGE_SIZE_MISMATCH', '검토된 이미지 크기를 초과했습니다.', 503)
            if len(header) < 104:
                header.extend(chunk[:104 - len(header)])
            digest.update(chunk)
            downloaded.write(chunk)
        if received != image.download_bytes or digest.hexdigest() != image.sha256:
            raise ImageError('IMAGE_INTEGRITY_FAILED', '공식 이미지 크기·SHA-256 검증에 실패했습니다. 업로드하지 않습니다.', 503)
        virtual_size = qcow2_virtual_size(header)
        if virtual_size != image.virtual_size_bytes:
            raise ImageError('IMAGE_SIZE_MISMATCH', '검토한 가상 디스크 크기와 일치하지 않습니다.', 503)
        downloaded.flush()
        downloaded.seek(0)
        heartbeat()
        return {'image_id': image.image_id, 'sha256': image.sha256,
                'download_bytes': received, 'virtual_size_bytes': virtual_size}
    except (OSError, ValueError, http.client.HTTPException):
        raise ImageError('IMAGE_DOWNLOAD_UNAVAILABLE', '공식 이미지 주소·TLS·임시 저장 공간 또는 통신을 확인하세요.', 503) from None
    finally:
        if connection is not None:
            connection.close()


@contextmanager
def verified_download(image_id, *, heartbeat=lambda: None):
    image = image_by_id(image_id)
    if not 104 <= image.download_bytes <= MAX_FILE_BYTES:
        raise ImageError('IMAGE_SIZE_REJECTED', '지원 이미지 크기 범위를 벗어났습니다.', 422)
    if not _download_slots.acquire(blocking=False):
        raise ImageError('IMAGE_DOWNLOAD_BUSY', '진행 중인 이미지 다운로드가 끝난 후 다시 검토하세요.', 429)
    try:
        try:
            downloaded = tempfile.TemporaryFile(prefix='gjallar-image-', suffix='.qcow2')
        except OSError:
            raise ImageError('IMAGE_STORAGE_UNAVAILABLE', '이미지 다운로드를 위한 임시 저장 공간을 확인하세요.', 503) from None
        with downloaded:
            observation = _download_into(image, downloaded, heartbeat)
            # Caller errors retain their own identity; cleanup is unconditional.
            yield downloaded, observation
    finally:
        _download_slots.release()
