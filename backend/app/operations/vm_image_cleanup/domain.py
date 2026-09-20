import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.cloud_images.catalog import ImageError


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    parent_operation_id: str = Field(pattern=r'^vm-image-build-[a-f0-9]{64}$')
    resource: Literal['template', 'source']
    idempotency_key: str = Field(min_length=1, max_length=160, pattern=r'^[A-Za-z0-9_.:-]+$')
    expected_name: str = Field(min_length=1, max_length=63)
    expected_review_digest: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    confirmation: str = Field(min_length=1, max_length=300)
    cleanup_acknowledged: bool


def check_expected(before, request):
    expected_confirmation = f"{before['vmid']}/{before['name']}/{before['resource']}"
    if request.cleanup_acknowledged is not True or request.confirmation != expected_confirmation:
        raise ImageError('IMAGE_CLEANUP_CONFIRMATION_REQUIRED', 'VMID/이름/정리 종류와 영구 삭제 영향을 확인하세요.', 422)
    if (request.expected_name != before['name'] or request.expected_review_digest != before['review_digest']
            or request.parent_operation_id != before['parent_operation_id'] or request.resource != before['resource']):
        raise ImageError('IMAGE_CLEANUP_REVIEW_CHANGED', '소유 작업·정리 자원이 검토 후 변경됐습니다. 다시 검토하세요.')


def task_reference(value, *, node_id, vmid, resource, storage):
    kind, target = ('qmdestroy', str(vmid)) if resource == 'template' else ('imgdel', storage)
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(
            rf'UPID:{re.escape(node_id)}:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:{kind}:{re.escape(target)}:[A-Za-z0-9_.@!+-]+:', value):
        raise ImageError('IMAGE_CLEANUP_TASK_UNKNOWN', '정확한 자원·노드의 삭제 task를 확인할 수 없습니다. 자동 재삭제하지 마세요.', 503)
    return value
