"""Admin-only setup routes; request/validation/upstream secrets never echo."""
import json
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_admin
from app.auth.roles import actor_evidence
from app.auth.sessions import current_session_id_from_request
from app.operations.core.domain import OperationActor
from app.setup_integration.contracts import RegistrationIntent, SetupError
from app.setup_integration.crypto import CredentialKeyError
from app.setup_integration.registration import service

router = APIRouter(prefix="/setup/proxmox/registrations", dependencies=[Depends(require_admin)])


def error(code="SETUP_INVALID_INPUT", message="연결 등록 입력이 올바르지 않습니다.", status=422):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 131072:
            raise error()
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise error() from None
    if not isinstance(result, dict):
        raise error()
    return result


async def call(function, **kwargs):
    try:
        result = await run_in_threadpool(function, **kwargs)
    except SetupError as exc:
        raise error(exc.code, str(exc), exc.status) from None
    except CredentialKeyError:
        raise error("SETUP_KEY_UNAVAILABLE", "서버 암호화 키를 확인하세요. 기존 키를 자동 생성하지 않습니다.", 503) from None
    except SQLAlchemyError:
        raise error("SETUP_STORAGE_UNAVAILABLE", "등록 상태를 저장·조회하지 못했습니다. 같은 요청의 상태를 다시 확인하세요.", 503) from None
    return success_response(result, meta={"mode": "proxmox_setup"})


@router.get("")
async def list_attempts(actor=Depends(require_admin)):
    return await call(service.repository.list, actor_id=actor.user_id)


@router.post("")
async def prepare(request: Request, actor=Depends(require_admin)):
    payload = await body(request)
    if set(payload) != {"intent", "idempotency_key"}:
        raise error()
    try:
        intent = RegistrationIntent.model_validate(payload["intent"])
        installation_id = str(uuid.UUID(os.environ.get("GJALLAR_INSTALLATION_ID", "")))
    except ValidationError:
        raise error() from None
    except ValueError:
        raise error("SETUP_INSTALLATION_ID_REQUIRED", "서버 installation identity 설정이 필요합니다.", 503) from None
    return await call(service.repository.prepare, intent=intent, idempotency_key=payload["idempotency_key"],
        actor=OperationActor.from_mapping(actor_evidence(actor)), installation_id=installation_id,
        cluster_id=str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip())


@router.post("/trust")
async def trust(request: Request, actor=Depends(require_admin)):
    from app.setup_integration.transport import ProxmoxSetupTransport
    payload = await body(request)
    if set(payload) != {"endpoint"} or not isinstance(payload["endpoint"], str) or len(payload["endpoint"]) > 512:
        raise error()
    try:
        endpoint = RegistrationIntent.endpoint_origin(payload["endpoint"])
    except ValueError:
        raise error() from None
    return await call(ProxmoxSetupTransport.probe_certificate, endpoint=endpoint)


@router.get("/{attempt_id}")
async def status(attempt_id: str, request: Request, actor=Depends(require_admin)):
    return await call(service.status, attempt_id=attempt_id, actor_id=actor.user_id,
                      session_id=current_session_id_from_request(request))


@router.post("/{attempt_id}/{action}")
async def action(attempt_id: str, action: str, request: Request, actor=Depends(require_admin)):
    payload = await body(request)
    fields = {"login": {"expected_version", "password", "otp"}, "mfa": {"expected_version", "otp"},
              "plan": {"expected_version"}, "confirm": {"expected_version", "plan_digest"},
              "verify": {"expected_version"}, "activate": {"expected_version"},
              "revoke": {"expected_version", "token_id"},
              "import-plan": {"expected_version"}, "import-env": {"expected_version", "plan_digest"},
              "observe": {"expected_version"}, "cancel": {"expected_version"}}
    if action not in fields:
        raise error("SETUP_ACTION_NOT_FOUND", "지원하지 않는 등록 작업입니다.", 404)
    required = fields[action] - ({"otp"} if action == "login" else set())
    if not required <= set(payload) or not set(payload) <= fields[action] or type(payload.get("expected_version")) is not int:
        raise error()
    function = getattr(service, action.replace("-", "_"))
    arguments = {**payload, "attempt_id": attempt_id, "actor_id": actor.user_id}
    if action in {"login", "mfa", "plan", "confirm", "observe", "revoke"}:
        arguments["session_id"] = current_session_id_from_request(request)
    return await call(function, **arguments)
