from copy import deepcopy
from datetime import datetime, timedelta, timezone
from difflib import unified_diff

import pytest

from app.db.session import session_scope
from app.operations.core.domain import verify_event_chain
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.host_config.admission import HostConfigurationAdmission
from app.operations.host_config.infrastructure import ConfigurationLockRepository
from app.operations.host_config.recovery import HostConfigurationRecoveryHandler
from app.operations.host_network.application import BridgeService
from app.operations.host_network.domain import BridgeChange, BridgeError, BridgeRequest
from app.operations.host_network.infrastructure import BridgeClient
from app.operations.recovery.domain import RecoveryLeaseLost
from app.operations.recovery.infrastructure.models import OperationRecoveryItemRecord
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.proxmox.client import ProxmoxMutationError


UPID = 'UPID:node1:ABC:123:456:srvreload:networking:root@pam:'


class FakeClient:
    def __init__(self):
        self.bridge = {'iface': 'vmbr40', 'type': 'bridge', 'families': ['inet'], 'method': 'manual',
            'autostart': 1, 'active': 1, 'bridge_ports': 'eno2', 'bridge_stp': 'off', 'bridge_fd': '0'}
        self.management = {'iface': 'vmbr0', 'type': 'bridge', 'address': '192.0.2.2', 'active': 1}
        self.changes = ''
        self.calls = []
        self.read_count = 0
        self.condition = None
        self.task_value = {'status': 'stopped', 'exitstatus': 'OK', 'upid': UPID,
                           'node': 'node1', 'id': 'networking', 'type': 'srvreload'}

    def get_host_network_permissions(self, *, node):
        return {f'/nodes/{node}': {'Sys.Audit', 'Sys.Modify'}, '/sdn/zones/localnetwork': {'SDN.Audit'}}

    def list_nodes(self):
        return [{'node': 'node1', 'status': 'online'}]

    def get_host_network_snapshot(self, *, node):
        self.read_count += 1
        if self.condition == 'precheck_drift' and self.read_count == 3:
            self.management['address'] = '192.0.2.3'
        if self.condition == 'before_reload_drift' and self.read_count == 5:
            self.management['address'] = '192.0.2.3'
        return deepcopy({'interfaces': [self.management, *([self.bridge] if self.bridge else [])], 'changes': self.changes})

    @staticmethod
    def render(row):
        if row is None:
            return ''
        result = ('auto vmbr40\n' if row.get('autostart') else '') + 'iface vmbr40 inet manual\n'
        result += '\tbridge-ports ' + (row.get('bridge_ports') or 'none') + '\n\tbridge-stp off\n\tbridge-fd 0\n'
        if row.get('bridge_vlan_aware'):
            result += '\tbridge-vlan-aware yes\n\tbridge-vids ' + row['bridge_vids'] + '\n'
        return result

    def stage_host_bridge(self, *, node, bridge, change):
        self.calls.append('stage')
        before = self.render(self.bridge)
        if self.bridge is None:
            self.bridge = {'iface': bridge, 'type': 'bridge', 'families': ['inet'], 'method': 'manual',
                           'bridge_ports': '', 'bridge_stp': 'off', 'bridge_fd': '0', 'active': 0}
        self.bridge.update({'autostart': int(change.autostart), 'bridge_vlan_aware': int(change.vlan_aware)})
        if change.vlan_aware:
            self.bridge['bridge_vids'] = change.vlan_ids
        else:
            self.bridge.pop('bridge_vids', None)
        after = self.render(self.bridge)
        if self.condition == 'foreign_diff':
            after += 'source /tmp/private-host-config\n'
        self.changes = ''.join(unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile='/etc/network/interfaces', tofile='/etc/network/interfaces.new', fromfiledate='before', tofiledate='after'))
        if self.condition == 'lost_stage':
            raise ProxmoxMutationError('private-token-test')
        return None

    def reload_host_network(self, *, node):
        self.calls.append('reload')
        self.changes = ''
        self.bridge['active'] = 1
        if self.condition == 'inactive':
            self.bridge['active'] = 0
        if self.condition == 'post_drift':
            self.management['address'] = '192.0.2.4'
        if self.condition == 'new_bridge_drift':
            self.bridge['mtu'] = 9000
        if self.condition == 'lost_reload':
            raise ProxmoxMutationError('private-token-test')
        if self.condition == 'wrong_upid':
            return UPID.replace('node1', 'node2')
        return UPID

    def wait_for_task(self, *, heartbeat, **kwargs):
        heartbeat()
        return self.get_task_status(**kwargs)

    def get_task_status(self, **kwargs):
        return deepcopy(self.task_value)


@pytest.fixture
def flow():
    fake = FakeClient()
    service = BridgeService(client=BridgeClient(fake), admission=HostConfigurationAdmission(),
        operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id='gjallar-mvp')
    return service, fake


def request(service, *, mode='update'):
    change = BridgeChange(mode=mode, vlan_aware=True, vlan_ids='10 20-30')
    plan = service.review(node_id='node1', bridge_id='vmbr40', change=change)
    return BridgeRequest(**change.model_dump(), idempotency_key='bridge-test', expected_review_digest=plan['review_digest'],
                         confirmation=plan['confirmation'], acknowledge_node_reload=True)


def execute(service, value):
    return service.execute(node_id='node1', bridge_id='vmbr40', request=value, actor={'user_id': 'admin', 'role': 'admin'})


def recover(service, operation_id):
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, operation_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    lease = service.recovery.claim_operation(operation_id, lease_owner='bridge-recovery', lease_seconds=60)
    return HostConfigurationRecoveryHandler(operation_type='host_network', operations=service.operations,
        recovery=service.recovery, service_factory=lambda: service, error_type=BridgeError).handle(lease)


@pytest.mark.parametrize('mode', ['create', 'update'])
def test_stage_reload_task_and_actual_observation_are_all_required(flow, mode):
    service, fake = flow
    if mode == 'create':
        fake.bridge = None
    value = request(service, mode=mode)
    result = execute(service, value)
    assert result['status'] == 'succeeded'
    assert result['staged_observation']['pending_changes'] is True
    assert result['observed_after']['pending_changes'] is False
    assert result['observed_after']['configuration']['active'] is True
    assert result['observed_after']['configuration']['ports'] == ([] if mode == 'create' else ['eno2'])
    assert fake.calls == ['stage', 'reload']
    assert '192.0.2.2' not in str(result)
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is None
    assert verify_event_chain(service.operations.list_events(result['operation_id']))
    assert execute(service, value)['idempotent_replay'] is True
    assert fake.calls == ['stage', 'reload']
    with pytest.raises(BridgeError):
        execute(service, value.model_copy(update={'autostart': False}))


@pytest.mark.parametrize('condition,writes', [
    ('lost_stage', ['stage']), ('foreign_diff', ['stage']), ('before_reload_drift', ['stage']),
    ('lost_reload', ['stage', 'reload']), ('wrong_upid', ['stage', 'reload']),
    ('inactive', ['stage', 'reload']), ('post_drift', ['stage', 'reload']),
])
def test_partial_failure_preserves_lock_and_get_only_recovery_never_completes_next_stage(flow, condition, writes):
    service, fake = flow
    value = request(service)
    fake.condition = condition
    result = execute(service, value)
    assert result['status'] == 'needs_reconciliation'
    assert fake.calls == writes
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is not None
    assert 'private-' not in str(result)
    assert recover(service, result['operation_id']).outcome == 'paused'
    assert fake.calls == writes
    if condition == 'inactive':
        fake.bridge['active'] = 1
        assert recover(service, result['operation_id']).outcome == 'succeeded'
        assert fake.calls == writes


def test_creation_preserves_verified_stage_options_through_reload(flow):
    service, fake = flow
    fake.bridge = None
    value = request(service, mode='create')
    fake.condition = 'new_bridge_drift'
    result = execute(service, value)
    assert result['status'] == 'needs_reconciliation'
    assert result['failure_code'] == 'HOST_NETWORK_CONFIGURATION_CHANGED'


def test_precheck_change_blocks_before_first_mutation(flow):
    service, fake = flow
    value = request(service)
    fake.condition = 'precheck_drift'
    with pytest.raises(BridgeError) as failure:
        execute(service, value)
    assert failure.value.code == 'HOST_NETWORK_STATE_CHANGED'
    assert fake.calls == []
    assert service.operations.list()[0].status == 'blocked'
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is None


@pytest.mark.parametrize('checkpoint', [
    'host_network_stage_dispatching', 'host_network_stage_acknowledged',
    'host_network_stage_verified', 'host_network_reload_dispatching', 'host_network_reload_task_bound',
])
def test_process_interruption_never_replays_or_advances_mutations(flow, monkeypatch, checkpoint):
    service, fake = flow
    value = request(service)
    original = service.checkpoint
    def interrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs['event'] == checkpoint:
            raise RuntimeError('simulated process exit')
        return result
    monkeypatch.setattr(service, 'checkpoint', interrupted)
    with pytest.raises(RuntimeError, match='simulated'):
        execute(service, value)
    operation = service.operations.list()[0]
    writes = list(fake.calls)
    result = recover(service, operation.operation_id)
    assert fake.calls == writes
    assert result.outcome == ('succeeded' if checkpoint == 'host_network_reload_task_bound' else 'paused')


def test_lease_loss_after_stage_prevents_reload(flow, monkeypatch):
    service, fake = flow
    value = request(service)
    original = service.checkpoint
    def lost(*args, **kwargs):
        if kwargs['event'] == 'host_network_stage_acknowledged':
            raise RecoveryLeaseLost(args[0].operation_id)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'checkpoint', lost)
    with pytest.raises(RecoveryLeaseLost):
        execute(service, value)
    assert fake.calls == ['stage']
    operation = service.operations.list()[0]
    assert recover(service, operation.operation_id).outcome == 'paused'
    assert fake.calls == ['stage']


@pytest.mark.parametrize('patch', [
    {'upid': UPID.replace('node1', 'node2')}, {'node': 'node2'}, {'id': 'other'}, {'type': 'qmstart'},
    {'exitstatus': 'private-error'},
])
def test_task_failure_or_wrong_identity_is_never_success(flow, patch):
    service, fake = flow
    fake.task_value.update(patch)
    result = execute(service, request(service))
    assert result['status'] == 'needs_reconciliation'
    assert 'private-error' not in str(result)
    assert ConfigurationLockRepository().current(cluster_id='gjallar-mvp') is not None


def test_task_binding_tampering_stops_before_task_query(flow, monkeypatch):
    service, fake = flow
    fake.condition = 'inactive'
    result = execute(service, request(service))
    with session_scope() as session:
        row = session.get(OperationRecoveryItemRecord, result['operation_id'])
        row.details = {**row.details, 'upid': UPID.replace('ABC', 'FFF')}
    def forbidden(**kwargs):
        pytest.fail('Must not query a mismatched task binding')
    monkeypatch.setattr(fake, 'get_task_status', forbidden)
    assert recover(service, result['operation_id']).outcome == 'paused'
    assert fake.calls == ['stage', 'reload']


def test_running_task_schedules_only_observation(flow):
    service, fake = flow
    fake.task_value['status'] = 'running'
    result = execute(service, request(service))
    assert result['status'] == 'running'
    assert recover(service, result['operation_id']).outcome == 'retry_wait'
    fake.task_value['status'] = 'stopped'
    # claim_operation is explicit recovery and may resume retry_wait before next_attempt_at.
    assert recover(service, result['operation_id']).outcome == 'succeeded'
    assert fake.calls == ['stage', 'reload']
