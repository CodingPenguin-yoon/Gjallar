"""Public credential selection and mutation admission boundary.

A process pins its source/revision on first use. A source change requires a
restart: old adapters can never dispatch a new operation with stale credentials.
"""
import os
import re
import threading
from weakref import WeakKeyDictionary
from urllib.parse import parse_qsl, urlsplit, unquote

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import session_scope
from app.setup_integration.contracts import SetupError
from app.setup_integration.crypto import CredentialCipher, CredentialKeyError
from app.setup_integration.models import ProxmoxConnectionRecord, ProxmoxCredentialRecord
from app.setup_integration.repository import decrypt_credential, lock_connection
from app.cloud_images.cleanup_contracts import cleanup_request_allowed
from app.operations.vm_migrate.domain import request_allowed as migrate_request_allowed
from app.operations.host_storage.domain import storage_request_allowed
from app.operations.host_network.domain import network_request_allowed as host_network_request_allowed
from app.backups.contracts import backup_request_allowed, restore_request_allowed, selected_archive
from app.cloud_images.catalog import image_by_id
from app.cloud_images.contracts import request_allowed as image_request_allowed, selected_import, upload_filename
from app.setup_integration.capabilities import clone_request_allowed, create_request_allowed, network_request_allowed, visible_vmids

_pins = WeakKeyDictionary()
_pin_lock = threading.Lock()


def _metrics_path(path, scope, vmids):
    parts = path.strip('/').split('/')
    if len(parts) not in {3, 5} or parts[0] != 'nodes' or parts[1] not in scope['nodes'] or parts[-1] != 'rrddata':
        return False
    if len(parts) == 3:
        return True
    return ((parts[2] == 'qemu' and parts[3].isdigit() and int(parts[3]) in vmids)
            or (parts[2] == 'storage' and parts[3] in scope['storages']))


def _metrics_query(data):
    return (isinstance(data, dict) and set(data) == {'timeframe', 'cf'}
            and data['timeframe'] in {'hour', 'day', 'week', 'month', 'year'} and data['cf'] == 'AVERAGE')


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
    feature = {"vm_start": "power", "vm_shutdown": "power", "vm_compute": "compute", "vm_create": "create", "vm_disk_resize": "disk", "vm_network": "network", "vm_clone": "clone", "vm_delete": "delete", "vm_template": "template", "vm_image_build": "image_build", "vm_image_cleanup": "image_cleanup", "vm_backup": "backup", "vm_restore": "restore", "vm_migrate": "migrate"}.get(operation_type)
    created_target = "create" in config["features"] and vmid in config["scope"].get("create_vmids", [])
    restored_target = "restore" in config["features"] and vmid in config["scope"].get("restore_vmids", [])
    if feature is None or (feature not in config["features"] and not ((created_target or restored_target) and feature == "power")):
        raise SetupError("SETUP_FEATURE_NOT_SELECTED", "현재 연결에서 이 작업의 권한을 선택하지 않았습니다.", 403)
    targets = config["scope"].get("create_vmids", []) if feature == "create" else list(config["scope"]["vmids"]) + list(config["scope"].get("create_vmids", []))
    if feature == "image_build":
        targets = config["scope"].get("image_vmids", [])
    if feature in {"template", "image_cleanup", "backup", "migrate"}:
        targets = config["scope"]["vmids"]
    if feature == "power" and restored_target:
        targets += list(config["scope"].get("restore_vmids", []))
    if feature == "restore":
        targets = list(config["scope"]["vmids"]) + list(config["scope"].get("restore_vmids", []))
    if feature == "clone":
        targets = list(config["scope"]["vmids"]) + list(config["scope"].get("clone_vmids", []))
    if vmid not in targets:
        raise SetupError("SETUP_TARGET_NOT_SELECTED", "현재 연결의 VM 범위에 포함되지 않습니다.", 403)
    try:
        decrypt_credential(CredentialCipher.configured(), connection, credential)
    except CredentialKeyError:
        raise SetupError("SETUP_CREDENTIAL_UNAVAILABLE", "연결 암호화 키를 확인하세요.", 503) from None


def admit_host_mutation(session, *, cluster_id, operation_type, target):
    from app.operations.host_config.domain import target_identity
    target_identity(operation_type, target)
    lock_connection(session)
    connection = session.get(ProxmoxConnectionRecord, 1)
    pin_selection(session.get_bind(), connection)
    if connection is None:
        return
    if connection.cluster_id != cluster_id or connection.admission != 'open':
        raise SetupError('SETUP_ADMISSION_CLOSED', '연결 전환 중이거나 cluster identity가 다릅니다.')
    if connection.source == 'legacy_env':
        return
    credential = session.get(ProxmoxCredentialRecord, connection.active_revision_id)
    if credential is None or credential.state != 'active':
        raise SetupError('SETUP_CREDENTIAL_UNAVAILABLE', '활성 인증정보를 확인할 수 없습니다.', 503)
    config = credential.configuration
    if operation_type not in config['features']:
        raise SetupError('SETUP_FEATURE_NOT_SELECTED', '현재 연결에서 호스트 설정 권한을 선택하지 않았습니다.', 403)
    scope = config['scope']
    resource_key, resource_id = (('host_storages', target['storage_id']) if operation_type == 'host_storage'
                                 else ('host_bridges', target['bridge_id']))
    if target['node_id'] not in scope['nodes'] or resource_id not in scope.get(resource_key, []):
        raise SetupError('SETUP_TARGET_NOT_SELECTED', '현재 연결의 호스트 설정 범위에 포함되지 않습니다.', 403)
    try:
        decrypt_credential(CredentialCipher.configured(), connection, credential)
    except CredentialKeyError:
        raise SetupError('SETUP_CREDENTIAL_UNAVAILABLE', '연결 암호화 키를 확인하세요.', 503) from None


class ManagedRequests:
    def __init__(self, selection):
        from app.setup_integration.transport import ProxmoxSetupTransport
        self.configuration = selection["configuration"]
        self.secret = selection["secret"]
        self.transport = ProxmoxSetupTransport(self.configuration["endpoint"], self.configuration["ca_pem"])

    def request(self, method, path, *, data=None, timeout=None, response_metadata=False, host_network_configuration=False):
        scope = self.configuration["scope"]
        if host_network_configuration and ('host_network' not in self.configuration['features'] or not response_metadata):
            raise SetupError('SETUP_FEATURE_NOT_SELECTED', '전체 네트워크 관찰은 host_network 선택이 필요합니다.', 403)
        if response_metadata and (method != "GET" or data is not None
                                  or path not in {f"/nodes/{node}/network" for node in scope["nodes"]}):
            raise SetupError("PROXMOX_REQUEST_INVALID", "이 조회에서는 응답 metadata를 사용할 수 없습니다.", 422)
        vmids = visible_vmids(scope)
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise SetupError("PROXMOX_REQUEST_INVALID", "지원하지 않는 API 경로입니다.", 422)
        if parsed.query:
            try:
                pairs = parse_qsl(parsed.query, strict_parsing=True)
            except ValueError:
                raise SetupError("PROXMOX_REQUEST_INVALID", "지원하지 않는 조회 조건입니다.", 422) from None
            if method != "GET" or data is not None or len(dict(pairs)) != len(pairs):
                raise SetupError("PROXMOX_REQUEST_INVALID", "지원하지 않는 조회 조건입니다.", 422)
            path, data = parsed.path, dict(pairs)
            if path == "/cluster/nextid":
                allowed = set(data) == {"vmid"} and data["vmid"] in {str(vmid) for vmid in vmids}
            elif path == "/cluster/resources":
                allowed = data == {"type": "vm"}
            elif path in {f"/nodes/{node}/storage/{storage}/content" for node in scope["nodes"] for storage in scope["storages"]}:
                allowed = ((set(data) == {"content", "vmid"} and (data["content"] == "images" and data["vmid"] in {str(vmid) for vmid in vmids}
                            or data["content"] == "backup" and bool({"backup", "restore"} & set(self.configuration["features"])) and data["vmid"] in {str(vmid) for vmid in scope["vmids"]} and path.split("/")[4] in scope.get("backup_storages", [])))
                           or (data == {"content": "import"} and bool({"image_build", "image_cleanup"} & set(self.configuration["features"]))))
            elif path in {f"/nodes/{node}/vzdump/extractconfig" for node in scope["nodes"]}:
                allowed = "restore" in self.configuration["features"] and set(data) == {"volume"} and selected_archive(data["volume"], scope)
            elif path in {f"/nodes/{node}/vzdump/defaults" for node in scope["nodes"]}:
                allowed = "backup" in self.configuration["features"] and set(data) == {"storage"} and data["storage"] in scope.get("backup_storages", [])
            elif path == "/access/permissions":
                allowed = set(data) == {"path"}
            elif _metrics_path(path, scope, vmids):
                allowed = _metrics_query(data)
            elif path in {f"/nodes/{node}/tasks" for node in scope["nodes"]}:
                allowed = (set(data) == {"source", "vmid"} and data["source"] == "active"
                           and data["vmid"] in {str(vmid) for vmid in vmids})
            elif path in {f"/nodes/{node}/qemu/{vmid}/migrate" for node in scope['nodes'] for vmid in scope['vmids']}:
                allowed = ("migrate" in self.configuration['features'] and set(data) == {'target'}
                           and data['target'] in scope['nodes'] and data['target'] != path.split('/')[2])
            elif path in {f"/nodes/{node}/qemu/{vmid}/config" for node in scope["nodes"] for vmid in vmids}:
                allowed = data == {"current": "1"}
            elif path in {f"/nodes/{node}/qemu/{vmid}/agent/exec-status" for node in scope["nodes"] for vmid in scope.get("create_vmids", [])}:
                allowed = "create" in self.configuration["features"] and set(data) == {"pid"} and data["pid"].isdigit() and int(data["pid"]) > 0
            else:
                allowed = False
            if not allowed:
                raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 조회입니다.", 403)
        pieces = path.strip("/").split("/")
        if path.endswith('/rrddata') and (method != 'GET' or not _metrics_path(path, scope, vmids) or not _metrics_query(data)):
            raise SetupError('SETUP_TARGET_NOT_SELECTED', '선택 범위와 지원 기간의 이력 조회만 허용합니다.', 403)
        if path == "/cluster/nextid" and method == "GET" and data and set(data) == {"vmid"} and str(data["vmid"]) in {str(vmid) for vmid in vmids}:
            pass
        elif path == "/cluster/resources" and method == "GET" and data == {"type": "vm"}:
            pass
        elif path == "/nodes" and method == "GET":
            pass
        elif path == '/storage' or path.startswith('/storage/'):
            if 'host_storage' not in self.configuration['features'] or not storage_request_allowed(method,path,data,scope):
                raise SetupError('SETUP_TARGET_NOT_SELECTED','선택한 호스트 storage의 허용된 설정 요청만 사용할 수 있습니다.',403)
        elif path == "/access/permissions" and method == "GET":
            allowed_paths = ({f"/nodes/{node}" for node in scope["nodes"]} | {f"/vms/{vmid}" for vmid in vmids}
                             | {f"/storage/{storage}" for storage in scope["storages"]}
                             | {f"/sdn/zones/localnetwork/{bridge}" for bridge in scope["bridges"]})
            if 'host_storage' in self.configuration['features']:
                allowed_paths |= {'/storage'} | {f'/storage/{storage}' for storage in scope.get('host_storages',[])}
            if 'host_network' in self.configuration['features']:
                allowed_paths.add('/sdn/zones/localnetwork')
            if not data or set(data) != {"path"} or data.get("path") not in allowed_paths:
                raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 권한 조회입니다.", 403)
        elif len(pieces) >= 3 and pieces[0] == "nodes" and pieces[1] in scope["nodes"]:
            if pieces[2] == 'network' and len(pieces) > 3 and method == 'GET':
                if ('host_network' not in self.configuration['features']
                        or not host_network_request_allowed(method, pieces, data, scope)):
                    raise SetupError('SETUP_TARGET_NOT_SELECTED', '선택한 host bridge만 조회할 수 있습니다.', 403)
            if pieces[2] == "vzdump" and method == "GET":
                defaults = (pieces[3:] == ["defaults"] and "backup" in self.configuration["features"] and isinstance(data, dict)
                            and set(data) == {"storage"} and data['storage'] in scope.get('backup_storages', []))
                extract = (pieces[3:] == ["extractconfig"] and "restore" in self.configuration["features"] and isinstance(data, dict)
                           and set(data) == {"volume"} and selected_archive(data['volume'], scope))
                if not (defaults or extract):
                    raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 백업 storage/VM archive 조회만 허용합니다.", 403)
            if pieces[2] == "storage" and len(pieces) >= 4:
                host_status = ('host_storage' in self.configuration['features'] and pieces[3] in scope.get('host_storages',[])
                               and method == 'GET' and pieces[4:] == ['status'] and data is None)
                if pieces[3] not in scope["storages"] and not host_status:
                    raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 storage입니다.", 403)
                if len(pieces) >= 5:
                    metrics_read = method == 'GET' and len(pieces) == 5 and (
                        (pieces[4] == 'rrddata' and _metrics_query(data)) or (pieces[4] == 'status' and data is None))
                    scoped_list = (method == "GET" and len(pieces) == 5 and pieces[4] == "content" and isinstance(data, dict)
                                   and set(data) == {"content", "vmid"} and data["content"] == "images"
                                   and str(data["vmid"]) in {str(vmid) for vmid in vmids})
                    import_list = (method == "GET" and len(pieces) == 5 and pieces[4] == "content"
                                   and data == {"content": "import"} and bool({"image_build", "image_cleanup"} & set(self.configuration["features"])))
                    backup_list = (method == "GET" and len(pieces) == 5 and pieces[4] == "content" and isinstance(data, dict)
                                   and set(data) == {"content", "vmid"} and data["content"] == "backup"
                                   and str(data["vmid"]) in {str(value) for value in scope['vmids']}
                                   and bool({"backup", "restore"} & set(self.configuration['features'])) and pieces[3] in scope.get('backup_storages', []))
                    if not (scoped_list or import_list or metrics_read or backup_list):
                        volume = unquote(pieces[5]) if len(pieces) == 6 and pieces[4] == "content" else ""
                        match = re.fullmatch(r"([A-Za-z0-9_.-]+):([0-9]+)/(?:vm|base)-([0-9]+)-(?:disk-[0-9]+|cloudinit)\.(raw|qcow2)", volume)
                        image_volume = (method in {"GET", "DELETE"} and bool({"image_build", "image_cleanup"} & set(self.configuration["features"]))
                                        and selected_import(volume, scope, include_existing="image_cleanup" in self.configuration["features"]) and volume.split(":", 1)[0] == pieces[3])
                        if not image_volume and (not match or match[1] != pieces[3] or match[2] != match[3] or int(match[2]) not in vmids):
                            raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 volume입니다.", 403)
            if pieces[2] == "qemu" and len(pieces) >= 4:
                if not pieces[3].isdigit() or int(pieces[3]) not in vmids:
                    raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 VM입니다.", 403)
            if pieces[2] == 'qemu' and pieces[4:] == ['migrate'] and method == 'GET':
                if ("migrate" not in self.configuration['features'] or int(pieces[3]) not in scope['vmids']
                        or not isinstance(data, dict) or set(data) != {'target'} or data['target'] not in scope['nodes']
                        or data['target'] == pieces[1]):
                    raise SetupError('SETUP_TARGET_NOT_SELECTED', '선택한 원본 VM/다른 목적 node의 이동 검토만 허용합니다.', 403)
            if method != "GET":
                existing_target = (len(pieces) >= 4 and pieces[2] == "qemu" and pieces[3].isdigit()
                                   and int(pieces[3]) in set(scope["vmids"]) | set(scope.get("create_vmids", [])))
                power = (existing_target and "power" in self.configuration["features"] and method == "POST"
                         and len(pieces) == 6 and pieces[2] == "qemu" and pieces[4] == "status"
                         and pieces[5] in {"start", "shutdown"})
                compute = (existing_target and "compute" in self.configuration["features"] and method == "PUT"
                           and len(pieces) == 5 and pieces[2] == "qemu" and pieces[4] == "config"
                           and isinstance(data, dict) and bool(set(data) & {"cores", "memory"})
                           and set(data) <= {"cores", "memory", "digest"})
                create = "create" in self.configuration["features"] and create_request_allowed(method, pieces, data, scope)
                disk = (existing_target and "disk" in self.configuration["features"] and method == "PUT" and len(pieces) == 5
                        and pieces[2] == "qemu" and pieces[4] == "resize" and isinstance(data, dict)
                        and set(data) == {"disk", "size", "digest"} and data["disk"] == "scsi0"
                        and isinstance(data["size"], str) and bool(re.fullmatch(r"[1-9][0-9]*G", data["size"]))
                        and isinstance(data["digest"], str) and bool(re.fullmatch(r"[a-fA-F0-9]{40}", data["digest"])))
                network = "network" in self.configuration["features"] and network_request_allowed(method, pieces, data, scope)
                host_network = 'host_network' in self.configuration['features'] and host_network_request_allowed(method, pieces, data, scope)
                clone = "clone" in self.configuration["features"] and clone_request_allowed(method, pieces, data, scope)
                template = (method == "POST" and len(pieces) == 5 and pieces[2] == "qemu" and pieces[3].isdigit()
                            and int(pieces[3]) in scope["vmids"] and pieces[4] == "template"
                            and "template" in self.configuration["features"] and data == {})
                image_build = "image_build" in self.configuration["features"] and image_request_allowed(method, pieces, data, scope)
                image_cleanup = "image_cleanup" in self.configuration["features"] and cleanup_request_allowed(method, pieces, data, scope)
                console = (len(pieces) == 5 and pieces[2] == "qemu" and pieces[3].isdigit()
                           and int(pieces[3]) in scope["vmids"] and "console" in self.configuration["features"]
                           and method == "POST" and pieces[4] == "vncproxy" and data == {"websocket": 1})
                delete = (existing_target and "delete" in self.configuration["features"] and method == "DELETE"
                          and len(pieces) == 4 and data == {"purge": 0, "destroy-unreferenced-disks": 0})
                migrate = "migrate" in self.configuration["features"] and migrate_request_allowed(method, pieces, data, scope)
                restore = "restore" in self.configuration["features"] and restore_request_allowed(method, pieces, data, scope)
                restore_power = (method == "POST" and "restore" in self.configuration["features"] and len(pieces) == 6
                                 and pieces[2] == "qemu" and pieces[3].isdigit() and int(pieces[3]) in scope.get("restore_vmids", [])
                                 and pieces[4:] in (["status", "start"], ["status", "shutdown"]) and data in (None, {}))
                backup = "backup" in self.configuration["features"] and backup_request_allowed(method, pieces, data, scope)
                if not (host_network or migrate or restore or restore_power or backup or power or compute or create or disk or network or clone or delete or console or template or image_build or image_cleanup):
                    raise SetupError("SETUP_FEATURE_NOT_SELECTED", "현재 연결에서 허용하지 않은 작업입니다.", 403)
        else:
            raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택 범위 밖의 요청입니다.", 403)
        options = {"response_metadata": True} if response_metadata else {}
        result = self.transport.request(method, path, data=data, token_id=self.configuration["token_id"],
                                        secret=self.secret, timeout=timeout, **options)
        metadata = None
        if response_metadata:
            if not isinstance(result, dict) or "data" not in result:
                raise SetupError("PROXMOX_PROTOCOL_ERROR", "Proxmox 네트워크 응답 metadata를 확인할 수 없습니다.", 502)
            metadata, result = result, result["data"]
        if method == "GET" and len(pieces) == 5 and pieces[2] == "storage" and pieces[4] == "content" and data == {"content": "import"}:
            if not isinstance(result, list) or any(not isinstance(row, dict) or not isinstance(row.get("volid"), str) for row in result):
                raise SetupError("PROXMOX_PROTOCOL_ERROR", "이미지 staging 목록을 확인할 수 없습니다.", 502)
            return [row for row in result if selected_import(row["volid"], scope, include_existing="image_cleanup" in self.configuration["features"]) and row["volid"].split(":", 1)[0] == pieces[3]]
        filter_key = None
        selected = None
        if method == "GET":
            if path == '/storage':
                filter_key, selected = 'storage', scope.get('host_storages',[])
            elif path == "/cluster/resources":
                filter_key, selected = "vmid", vmids
            elif path == "/nodes":
                filter_key, selected = "node", scope["nodes"]
            elif len(pieces) == 3 and pieces[2] in {"qemu", "storage", "network"}:
                filter_key, selected = {"qemu": ("vmid", vmids), "storage": ("storage", scope["storages"]),
                                        "network": ("iface", scope["bridges"])}[pieces[2]]
                if pieces[2] == 'storage' and 'host_storage' in self.configuration['features']:
                    selected = list(selected) + scope.get('host_storages',[])
                if pieces[2] == 'network' and host_network_configuration:
                    # Only the explicit host-config observation compares every interface.
                    # VM NIC choices and ordinary inventory retain their original scope.
                    filter_key = None
        if filter_key:
            if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
                raise SetupError("PROXMOX_PROTOCOL_ERROR", "Proxmox 목록 응답 형식이 올바르지 않습니다.", 502)
            if path == "/cluster/resources" and any(type(item.get("vmid")) is not int for item in result):
                raise SetupError("PROXMOX_PROTOCOL_ERROR", "VMID 점유 여부를 확인할 수 없습니다.", 502)
            if path == '/storage' and any(not isinstance(item.get('storage'),str) for item in result):
                raise SetupError('PROXMOX_PROTOCOL_ERROR','storage ID 존재 여부를 확인할 수 없습니다.',502)
            result = [item for item in result if item.get(filter_key) in selected]
        return {**metadata, "data": result} if metadata is not None else result

    def image_base_dependents(self, *, node, vmid, storage, volume):
        """Observe backing references without exposing unrelated VM/storage content."""
        scope = self.configuration["scope"]
        if ("image_cleanup" not in self.configuration["features"] or node not in scope["nodes"]
                or type(vmid) is not int or vmid not in scope["vmids"]
                or storage not in scope.get("image_cleanup_storages", [])
                or not isinstance(volume, str)
                or not re.fullmatch(rf"{re.escape(storage)}:{vmid}/base-{vmid}-disk-[0-9]+\.qcow2", volume)):
            raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택한 제작 template·정리 storage 범위를 확인하세요.", 403)
        permissions = self.request("GET", "/access/permissions", data={"path": f"/storage/{storage}"})
        if "Datastore.Allocate" not in permissions.get(f"/storage/{storage}", {}):
            raise SetupError("SETUP_CLEANUP_OBSERVATION_DENIED", "다른 VM의 backing 참조를 빠짐없이 확인할 storage Allocate 권한이 필요합니다.", 403)
        rows = self.transport.request("GET", f"/nodes/{node}/storage/{storage}/content", data={"content": "images"},
                                      token_id=self.configuration["token_id"], secret=self.secret)
        if (not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("volid"), str)
                or not row["volid"].startswith(storage + ":") or ("parent" in row and not isinstance(row["parent"], str)) for row in rows)):
            raise SetupError("PROXMOX_PROTOCOL_ERROR", "template backing 참조 목록을 확인할 수 없습니다.", 502)
        # PVE file storage also encodes base references in the volume identifier.
        return {"volume_id": volume, "dependent_count": sum(1 for row in rows
                if row.get("parent") == volume or row["volid"].startswith(volume + "/"))}

    def upload_image(self, *, node, vmid, storage, operation_id, image_id, file, heartbeat):
        scope = self.configuration["scope"]
        if ("image_build" not in self.configuration["features"] or node not in scope["nodes"]
                or type(vmid) is not int or vmid not in scope.get("image_vmids", []) or storage not in scope["storages"]):
            raise SetupError("SETUP_TARGET_NOT_SELECTED", "선택한 이미지 제작 VMID·노드·storage 범위를 확인하세요.", 403)
        image = image_by_id(image_id)
        return self.transport.upload_import(node=node, storage=storage, filename=upload_filename(vmid, operation_id),
            file=file, size=image.download_bytes, sha256=image.sha256, token_id=self.configuration["token_id"],
            secret=self.secret, heartbeat=heartbeat)

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


def console_selection(*, node_id, vmid):
    """Read the selected console capability without creating a VM mutation lock."""
    selection = selected_credential()
    with session_scope() as session:
        connection = session.get(ProxmoxConnectionRecord, 1)
        pin_selection(session.get_bind(), connection)
        if connection is not None and connection.admission != "open":
            raise SetupError("SETUP_ADMISSION_CLOSED", "연결 전환 중에는 콘솔을 열 수 없습니다.")
    if selection:
        config = selection["configuration"]
        if "console" not in config["features"]:
            raise SetupError("SETUP_FEATURE_NOT_SELECTED", "현재 연결에서 콘솔 권한을 선택하지 않았습니다.", 403)
        if node_id not in config["scope"]["nodes"] or vmid not in config["scope"]["vmids"]:
            raise SetupError("SETUP_TARGET_NOT_SELECTED", "현재 연결의 콘솔 대상 범위에 포함되지 않습니다.", 403)
    return selection
