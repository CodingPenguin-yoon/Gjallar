"""Selected-connection GET adapter; does not execute guest or host commands."""
from app.monitoring.domain import MonitoringError
from app.proxmox.client import ProxmoxMutationError, get_default_proxmox_mutation_client
from app.setup_integration.contracts import SetupError


class MonitoringClient:
    def __init__(self, client):
        self.client = client

    def _read(self, target, timeframe=None):
        try:
            return self.client.get_monitoring_data(kind=target.kind, node=target.node_id,
                vmid=target.vmid, storage=target.storage_id, timeframe=timeframe)
        except SetupError as exc:
            raise MonitoringError(exc.code, str(exc), exc.status) from None
        except ProxmoxMutationError as exc:
            denied = exc.details.get('status_code') == 403
            raise MonitoringError('MONITORING_PERMISSION_DENIED' if denied else 'MONITORING_SOURCE_UNAVAILABLE',
                '연결의 조회 범위·권한을 확인하세요.' if denied else 'PVE 관찰 응답을 읽지 못했습니다.', 403 if denied else 502) from None

    def current(self, target):
        return self._read(target)

    def history(self, target, timeframe):
        return self._read(target, timeframe)


def monitoring_service():
    from app.monitoring.application import MonitoringService
    try:
        client = get_default_proxmox_mutation_client()
    except (ProxmoxMutationError, SetupError):
        raise MonitoringError('MONITORING_CONNECTION_UNAVAILABLE', '선택된 Proxmox 연결을 확인하세요.', 503) from None
    return MonitoringService(MonitoringClient(client))
