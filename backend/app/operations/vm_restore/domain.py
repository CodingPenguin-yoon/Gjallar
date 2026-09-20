import hashlib
import re
from pydantic import BaseModel, ConfigDict, Field
from app.backups.contracts import ID, ARCHIVE
from app.backups.domain import BackupError


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    archive: str = Field(pattern=rf'^{ARCHIVE}$', max_length=255)
    new_vmid: int = Field(ge=100,le=999999999)
    name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]{0,62}$')
    storage_id: str = Field(pattern=rf'^{ID}$')
    bridge_id: str = Field(pattern=rf'^{ID}$')
    idempotency_key: str = Field(min_length=1,max_length=160,pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_name: str = Field(min_length=1,max_length=255)
    expected_review_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(min_length=1,max_length=300)
    isolation_acknowledged: bool


def isolated_mac(*, archive, node, new_vmid, source_mac):
    raw=bytearray(hashlib.sha256(f'{archive}:{node}:{new_vmid}'.encode()).digest()[:6])
    raw[0]=2
    value=':'.join(f'{part:02X}' for part in raw)
    if value == source_mac.upper(): raw[-1] ^= 1
    return ':'.join(f'{part:02X}' for part in raw)


def check_expected(before, request):
    if (request.isolation_acknowledged is not True
            or request.confirmation != f"{before['vmid']}/{request.new_vmid}/{request.name}"):
        raise BackupError('VM_RESTORE_CONFIRMATION_REQUIRED','원본/새 VMID/이름과 격리 복원 영향을 확인하세요.',422)
    if request.expected_name != before['name'] or request.expected_review_digest != before['review_digest']:
        raise BackupError('VM_RESTORE_STATE_CHANGED','원본·archive·복원 대상이 검토 후 변경됐습니다. 다시 검토하세요.')


def task_reference(value, *, node_id, vmid):
    if not isinstance(value,str) or len(value)>512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:qmrestore:{vmid}:[A-Za-z0-9_.@!+-]+:',value):
        raise BackupError('VM_RESTORE_TASK_UNKNOWN','정확한 새 VM·노드의 restore task를 확인하지 못했습니다. 자동 재복원하지 마세요.',503)
    return value
