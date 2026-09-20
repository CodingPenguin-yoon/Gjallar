"""Bounded bidirectional console relay with continuous Gjallar session checks."""
import asyncio
from contextlib import contextmanager
import threading

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect, WebSocketState
from websockets.exceptions import ConnectionClosed

from app.auth.config import allowed_origins, session_cookie_name
from app.auth.roles import role_at_least
from app.auth.sessions import actor_for_session_token
from app.console.domain import ConsoleError, validate_target
from app.console.infrastructure import console_client
from app.setup_integration.contracts import SetupError

MAX_DURATION = 900
AUTH_INTERVAL = 5
_counts = {}
_counts_lock = threading.Lock()


@contextmanager
def connection_slot(user_id):
    with _counts_lock:
        if sum(_counts.values()) >= 32 or _counts.get(user_id, 0) >= 2:
            raise ConsoleError('CONSOLE_CAPACITY', '열려 있는 콘솔을 종료한 뒤 다시 연결하세요.', 429)
        _counts[user_id] = _counts.get(user_id, 0) + 1
    try:
        yield
    finally:
        with _counts_lock:
            _counts[user_id] -= 1
            if not _counts[user_id]:
                del _counts[user_id]


def authenticated_actor(token):
    actor = actor_for_session_token(token)
    if actor is None or not role_at_least(actor.role, 'operator'):
        raise ConsoleError('CONSOLE_SESSION_REQUIRED', '유효한 operator 로그인 세션이 필요합니다.', 403)
    return actor


async def relay(websocket, upstream, *, token, actor, client, max_duration=MAX_DURATION, auth_interval=AUTH_INTERVAL):
    async def browser_to_pve():
        while True:
            message = await websocket.receive()
            if message['type'] == 'websocket.disconnect':
                return
            data = message.get('bytes')
            if data is None or len(data) > 128 * 1024:
                raise ConsoleError('CONSOLE_FRAME_REJECTED', '지원하지 않는 콘솔 입력입니다.', 422)
            # PVE rejects fragmented or >128 KiB frames; explicit small sends are unfragmented.
            for start in range(0, len(data), 64 * 1024):
                await upstream.send(data[start:start + 64 * 1024])

    async def pve_to_browser():
        async for data in upstream:
            if not isinstance(data, bytes):
                raise ConsoleError('CONSOLE_FRAME_REJECTED', '지원하지 않는 PVE 콘솔 응답입니다.', 502)
            await websocket.send_bytes(data)

    async def validate_session():
        while True:
            await asyncio.sleep(auth_interval)
            current = await run_in_threadpool(authenticated_actor, token)
            if current.user_id != actor.user_id:
                raise ConsoleError('CONSOLE_SESSION_REQUIRED', '콘솔 로그인 세션이 변경됐습니다.', 403)
            await run_in_threadpool(client.check_selection)

    tasks = [asyncio.create_task(action()) for action in (browser_to_pve, pve_to_browser, validate_session)]
    try:
        done, _ = await asyncio.wait(tasks, timeout=max_duration, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            return 4408, 'CONSOLE_EXPIRED'
        for task in done:
            task.result()
        return 1000, 'CONSOLE_CLOSED'
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def serve_console(websocket, *, node_id, vmid):
    close_code, reason = 1011, 'CONSOLE_UNAVAILABLE'
    try:
        validate_target(node_id, vmid)
        if websocket.query_params or websocket.headers.get('origin') not in allowed_origins():
            raise ConsoleError('CONSOLE_ORIGIN_REJECTED', '허용된 웹 origin에서만 콘솔에 접속할 수 있습니다.', 403)
        token = websocket.cookies.get(session_cookie_name())
        actor = await run_in_threadpool(authenticated_actor, token)
        with connection_slot(actor.user_id):
            client = await run_in_threadpool(console_client, node_id=node_id, vmid=vmid)
            await websocket.accept()
            ticket = await run_in_threadpool(client.prepare)
            # Recheck after potentially slow PVE calls, before opening the data stream.
            await run_in_threadpool(authenticated_actor, token)
            await run_in_threadpool(client.check_selection)
            async with client.open(ticket) as upstream:
                await websocket.send_json({'type': 'ready', 'password': ticket.password, 'expires_in': MAX_DURATION})
                close_code, reason = await relay(websocket, upstream, token=token, actor=actor, client=client)
    except (ConsoleError, SetupError) as exc:
        close_code, reason = (4403 if exc.status == 403 else 4409), exc.code
    except (SQLAlchemyError, OSError, TimeoutError):
        close_code, reason = 1011, 'CONSOLE_UNAVAILABLE'
    except (WebSocketDisconnect, ConnectionClosed):
        close_code, reason = 1000, 'CONSOLE_CLOSED'
    finally:
        if (websocket.application_state != WebSocketState.DISCONNECTED
                and websocket.client_state != WebSocketState.DISCONNECTED):
            await websocket.close(code=close_code, reason=reason)
