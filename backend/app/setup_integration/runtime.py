"""Public credential selection and mutation admission boundary.

A process pins its source/revision on first use. A source change requires a
restart: old adapters can never dispatch a new operation with stale credentials.
"""
import os
import threading
from weakref import WeakKeyDictionary

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import session_scope
from app.setup_integration.contracts import SetupError
from app.setup_integration.crypto import CredentialCipher, CredentialKeyError
from app.setup_integration.models import ProxmoxConnectionRecord, ProxmoxCredentialRecord
from app.setup_integration.repository import decrypt_credential, lock_connection

_pins = WeakKeyDictionary()
_pin_lock = threading.Lock()


def pin_selection(engine, connection):
    selection = (connection.source, connection.active_revision_id) if connection else ("legacy_env", None)
    with _pin_lock:
        previous = _pins.setdefault(engine, selection)
    if previous != selection:
        raise SetupError("SETUP_RESTART_REQUIRED", "Proxmox 연결이 변경됐습니다. 모든 Gjallar 서비스를 재시작하세요.", 503)


def selected_credential():
    try:
        with session_scope() as session:
            connection = session.get(ProxmoxConnectionRecord, 1)
            pin_selection(session.get_bind(), connection)
            if connection is None or connection.source == "legacy_env":
                return None
            if connection.cluster_id != str(os.getenv("GJALLAR_CLUSTER_ID") or "gjallar-mvp").strip():
                raise SetupError("SETUP_CLUSTER_MISMATCH", "저장된 연결과 cluster identity가 다릅니다.", 503)
            credential = session.get(ProxmoxCredentialRecord, connection.active_revision_id)
            if credential is None or credential.state != "active":
                raise SetupError("SETUP_CREDENTIAL_UNAVAILABLE", "활성 인증정보를 확인할 수 없습니다.", 503)
            secret = decrypt_credential(CredentialCipher.configured(), connection, credential)
            return {"revision_id": credential.revision_id, "cluster_id": connection.cluster_id,
                    "configuration": dict(credential.configuration), "secret": secret}
    except (SQLAlchemyError, CredentialKeyError):
        raise SetupError("SETUP_CREDENTIAL_UNAVAILABLE", "연결 저장소 또는 암호화 키를 확인하세요. 환경변수로 자동 전환하지 않습니다.", 503) from None


def admit_mutation(session, *, cluster_id, vmid, operation_type):
    lock_connection(session)
    connection = session.get(ProxmoxConnectionRecord, 1)
    pin_selection(session.get_bind(), connection)
    if connection is None:
        return
    if connection.cluster_id != cluster_id or connection.admission != "open":
        raise SetupError("SETUP_ADMISSION_CLOSED", "연결 전환 중이거나 cluster identity가 다릅니다.")
    if connection.source == "legacy_env":
        return
    credential = session.get(ProxmoxCredentialRecord, connection.active_revision_id)
    if credential is None or credential.state != "active":
        raise SetupError("SETUP_CREDENTIAL_UNAVAILABLE", "활성 인증정보를 확인할 수 없습니다.", 503)
    config = credential.configuration
    # The initial managed profile supports reads and optional power operations.
    if operation_type not in {"vm_start", "vm_shutdown"} or "power" not in config["features"]:
        raise SetupError("SETUP_FEATURE_NOT_SELECTED", "현재 연결에서 이 작업의 권한을 선택하지 않았습니다.", 403)
    if vmid not in config["scope"]["vmids"]:
        raise SetupError("SETUP_TARGET_NOT_SELECTED", "현재 연결의 VM 범위에 포함되지 않습니다.", 403)
    try:
        decrypt_credential(CredentialCipher.configured(), connection, credential)
    except CredentialKeyError:
        raise SetupError("SETUP_CREDENTIAL_UNAVAILABLE", "연결 암호화 키를 확인하세요.", 503) from None


class ManagedRequests:
    def __init__(self, selection):
        from app.setup_integration.transport import ProxmoxSetupTransport
        self.configuration = selection["configuration"]
        self.secret = selection["secret"]
        self.transport = ProxmoxSetupTransport(self.configuration["endpoint"], self.configuration["ca_pem"])

    def request(self, method, path, *, data=None, timeout=None):
        scope = self.configuration["scope"]
        pieces = path.strip("/").split("/")
        if path == "/nodes" and method == "GET":
            pass
        elif path == "/access/permissions" and method == "GET":
            if not data or data.get("path") not in {f"/nodes/{node}" for node in scope["nodes"]}:
                raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 권한 조회입니다.", 403)
        elif len(pieces) >= 3 and pieces[0] == "nodes" and pieces[1] in scope["nodes"]:
            if pieces[2] == "qemu" and len(pieces) >= 4:
                if not pieces[3].isdigit() or int(pieces[3]) not in scope["vmids"]:
                    raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 VM입니다.", 403)
            if method != "GET":
                if ("power" not in self.configuration["features"] or method != "POST"
                        or len(pieces) != 6 or pieces[2] != "qemu" or pieces[4] != "status"
                        or pieces[5] not in {"start", "shutdown"}):
                    raise SetupError("SETUP_FEATURE_NOT_SELECTED", "현재 연결에서 허용하지 않은 작업입니다.", 403)
        else:
            raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 요청입니다.", 403)
        result = self.transport.request(method, path, data=data, token_id=self.configuration["token_id"],
                                        secret=self.secret, timeout=timeout)
        filter_key = None
        selected = None
        if method == "GET":
            if path == "/nodes":
                filter_key, selected = "node", scope["nodes"]
            elif len(pieces) == 3 and pieces[2] in {"qemu", "storage", "network"}:
                filter_key, selected = {"qemu": ("vmid", scope["vmids"]), "storage": ("storage", scope["storages"]),
                                        "network": ("iface", scope["bridges"])}[pieces[2]]
        if filter_key:
            if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
                raise SetupError("PROXMOX_PROTOCOL_ERROR", "Proxmox 목록 응답 형식이 올바르지 않습니다.", 502)
            return [item for item in result if item.get(filter_key) in selected]
        return result

    def get(self, path, *, timeout=None):
        return self.request("GET", path, timeout=timeout)


def managed_inventory_adapter(selection):
    from app.proxmox.inventory import LiveProxmoxInventoryAdapter
    config = selection["configuration"]
    requests = ManagedRequests(selection)
    return LiveProxmoxInventoryAdapter(api_url=config["endpoint"], token_id=config["token_id"], token_secret=selection["secret"],
        request_get=requests.get, cluster_id=selection["cluster_id"])


def managed_mutation_client(selection):
    from app.proxmox.client import ProxmoxMutationClient
    config = selection["configuration"]
    requests = ManagedRequests(selection)
    return ProxmoxMutationClient(api_url=config["endpoint"], token_id=config["token_id"], token_secret=selection["secret"],
        request=requests.request)
