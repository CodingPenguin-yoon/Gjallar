import re
from pydantic import BaseModel, ConfigDict, Field
from app.backups.domain import BackupError
from app.backups.contracts import ID


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    storage_id: str = Field(pattern=rf'^{ID}$')
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_name: str = Field(min_length=1, max_length=255)
    expected_review_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(min_length=1, max_length=300)
    backup_acknowledged: bool


def check_expected(before, request):
    if request.backup_acknowledged is not True or request.confirmation != f"{before['vmid']}/{before['name']}":
        raise BackupError('VM_BACKUP_CONFIRMATION_REQUIRED', 'VMID/이름과 백업의 공간·IO 영향을 확인하세요.', 422)
    if request.expected_name != before['name'] or request.expected_review_digest != before['review_digest']:
        raise BackupError('VM_BACKUP_STATE_CHANGED', '검토 후 원본·백업 목록·기본값이 변경됐습니다. 다시 검토하세요.')


def task_reference(value, *, node_id, vmid):
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:vzdump:{vmid}:[A-Za-z0-9_.@!+-]+:', value):
        raise BackupError('VM_BACKUP_TASK_UNKNOWN', '정확한 VM·노드의 백업 task를 확인할 수 없습니다. 자동 재백업하지 마세요.', 503)
    return value
