"""Reviewed image releases; never follow a mutable latest alias at execution time."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CloudImage:
    image_id: str
    label: str
    url: str
    sha256: str
    download_bytes: int
    virtual_size_bytes: int
    signature_fingerprint: str
    checksum_url: str

    def public(self):
        return asdict(self)


ALMA_9 = CloudImage(
    image_id='almalinux-9.8-x86_64-20260810',
    label='AlmaLinux 9.8 GenericCloud x86_64 (2026-08-10)',
    url='https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-9.8-20260810.x86_64.qcow2',
    sha256='6bdab6376d46d42e4203ace3733efafc7c5d37c7cb443a6cc74750097002d74b',
    download_bytes=589299712,
    virtual_size_bytes=10737418240,
    signature_fingerprint='BF18AC2876178908D6E71267D36CB86CB86B3716',
    checksum_url='https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/CHECKSUM',
)
CATALOG = {ALMA_9.image_id: ALMA_9}


class ImageError(RuntimeError):
    def __init__(self, code, message, status_code=409, details=None):
        super().__init__(message)
        self.code, self.status_code, self.details = code, status_code, details or {}

    def to_detail(self):
        return {'code': self.code, 'message': str(self), 'details': self.details}


def image_by_id(image_id):
    if image_id not in CATALOG:
        raise ImageError('IMAGE_UNSUPPORTED', '지원하는 공식 cloud image를 선택하세요.', 422)
    return CATALOG[image_id]
