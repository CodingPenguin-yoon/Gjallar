"""Authenticated console review and cookie-bound WebSocket entry point."""
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.v1.responses import success_response
from app.auth.dependencies import require_operator
from app.auth.roles import AuthenticatedUser
from app.console.domain import ConsoleError
from app.console.gateway import serve_console
from app.console.infrastructure import console_client
from app.setup_integration.contracts import SetupError

router = APIRouter()
# WebSocket auth is checked explicitly; HTTP Request dependencies cannot handle an upgrade.
websocket_router = APIRouter(prefix='/api/v1')


def _review(node_id, vmid):
    try:
        return console_client(node_id=node_id, vmid=vmid).review()
    except (ConsoleError, SetupError) as exc:
        raise HTTPException(exc.status, detail={'code': exc.code, 'message': str(exc)}) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={'code': 'CONSOLE_UNAVAILABLE', 'message': '연결 저장소를 확인할 수 없습니다.'}) from None


@router.get('/nodes/{node_id}/vms/{vmid}/console')
async def review_console(node_id: str, vmid: int, actor: AuthenticatedUser = Depends(require_operator)):
    return success_response(await run_in_threadpool(_review, node_id, vmid))


@websocket_router.websocket('/nodes/{node_id}/vms/{vmid}/console/socket')
async def console_socket(websocket: WebSocket, node_id: str, vmid: int):
    await serve_console(websocket, node_id=node_id, vmid=vmid)
