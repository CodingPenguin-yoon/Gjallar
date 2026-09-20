import copy
from datetime import datetime, timedelta, timezone
import pytest
from app.maintenance.application import MaintenanceError, MaintenanceService

NOW = datetime(2026, 9, 19, 9, tzinfo=timezone.utc)


@pytest.fixture
def flow():
    vm = {'node_id': 'node1', 'vmid': 40000, 'name': 'test', 'status': 'stopped', 'template': False,
        'cpu': 2, 'memory_mb': 2048, 'storage_id': 'nfs', 'disks': [{'storage_id': 'nfs'}],
        'nic_bridge_evidence': [{'bridge_id': 'vmbr1'}]}
    snapshot = {'observed_at': NOW.isoformat(), 'nodes': [{'node_id': 'node1', 'status': 'online', 'cpu_total': 16,
        'memory_total_mb': 32000, 'storage': [], 'networks': []}], 'vms': [vm], 'templates': [],
        'availability': {'complete': True, 'sources': {name: {'complete': True} for name in ('storage','network','vm_config','vm_detail','guest_agent')}}}
    calls = []
    def migration(**kwargs):
        calls.append(('migration', kwargs))
        return {'target': {'node_id': kwargs['node_id'], 'vmid': kwargs['vmid']},
            'observed_before': {'name': 'test', 'destination': {'node_id': kwargs['destination_node']}}}
    def backup(**kwargs):
        calls.append(('backup', kwargs))
        return {'target': {'node_id': kwargs['node_id'], 'vmid': kwargs['vmid'], 'storage_id': kwargs['storage']},
            'archives': [{'volume_id': 'nfs:backup/archive', 'created_at': int(NOW.timestamp()) - 3600, 'size_bytes': 1024}]}
    service = MaintenanceService(lambda: {'snapshot': snapshot}, migration, backup, clock=lambda: NOW)
    return service, snapshot, calls


def report(flow, **kwargs):
    return flow[0].report(**{'node_id': 'node1', 'destination_node': 'node2', 'backup_storage': 'nfs', **kwargs})


def test_prepared_is_not_executed_or_node_shutdown_authorization(flow):
    result = report(flow)
    assert result['checks_complete'] and result['status'] == 'preparation_checked'
    assert result['prepared_target_count'] == 1 and result['node_shutdown_safe'] is False
    assert result['targets'][0]['preparation'] == 'ready_for_manual_migration'
    assert result['targets'][0]['still_on_source'] and result['targets'][0]['backup']['restore_verified'] is False
    assert result['coverage'] == 'visible_qemu_only' and result['read_only']
    assert [kind for kind, _ in flow[2]] == ['migration', 'backup']


@pytest.mark.parametrize('options', [{'destination_node': None}, {'backup_storage': None}])
def test_optional_inputs_do_not_claim_complete(flow, options):
    result = report(flow, **options)
    assert result['status'] == 'incomplete' and not result['checks_complete']
    assert len(flow[2]) == 1


@pytest.mark.parametrize('stamp', ['', 'invalid', (NOW-timedelta(minutes=6)).isoformat(), (NOW+timedelta(seconds=1)).isoformat(), NOW.replace(tzinfo=None).isoformat()])
def test_missing_stale_future_or_naive_snapshot_does_not_check_or_claim_ready(flow, stamp):
    flow[1]['observed_at'] = stamp
    result = report(flow)
    assert result['status'] == 'unavailable' and not flow[2]


def test_missing_base_and_missing_node_are_distinct(flow):
    flow[0].inventory = lambda: {'snapshot': None}
    assert report(flow)['status'] == 'unavailable'
    flow[0].inventory = lambda: {'snapshot': flow[1]}
    with pytest.raises(MaintenanceError) as error: report(flow, node_id='hidden')
    assert error.value.status_code == 404


@pytest.mark.parametrize('source', ['vm_config','vm_detail','storage','network'])
def test_partial_required_inventory_cannot_be_ready(flow, source):
    flow[1]['availability']['sources'][source]['complete'] = False
    assert report(flow)['status'] == 'unavailable' and not flow[2]


def test_optional_guest_agent_missing_does_not_block_stopped_vm_preparation(flow):
    flow[1]['availability']['complete'] = False
    flow[1]['availability']['sources']['guest_agent']['complete'] = False
    assert report(flow)['checks_complete']


def test_empty_visible_scope_is_not_a_cleared_node(flow):
    flow[1]['vms'] = []
    result = report(flow)
    assert result['status'] == 'no_visible_targets' and not result['checks_complete'] and not result['node_shutdown_safe']


def test_running_template_and_duplicate_require_separate_action(flow):
    original = flow[1]['vms'][0]
    flow[1]['vms'] = [{**original, 'status': 'running'}, {**original, 'vmid': 40001}, {**original, 'vmid': 40001}]
    flow[1]['templates'] = [{**original, 'vmid': 9000, 'template': True}]
    result = report(flow)
    assert [row['migration']['status'] for row in result['targets']] == ['unsupported','blocked','unavailable','unavailable']
    assert len(flow[2]) == 1 and flow[2][0][0] == 'backup'


def test_template_present_in_both_collections_is_counted_once(flow):
    flow[1]['vms'][0]['template'] = True
    flow[1]['templates'] = [copy.deepcopy(flow[1]['vms'][0])]
    assert report(flow)['total_observed_targets'] == 1


def test_bounded_checks_and_bounded_impact_list_are_explicit(flow):
    vm = flow[1]['vms'][0]
    flow[1]['vms'] = [{**vm, 'vmid': 40000+i} for i in range(205)]
    result = report(flow, check_limit=2)
    assert result['total_observed_targets'] == 205 and len(result['targets']) == 200 and result['truncated']
    assert len(flow[2]) == 4 and result['checked_target_count'] == result['prepared_target_count'] == 2
    assert result['targets'][2]['migration']['status'] == 'not_checked' and not result['checks_complete']


@pytest.mark.parametrize('age,expected', [(-1,'unavailable'),(3600*24,'recent_archive'),(3600*24+1,'old_archive')])
def test_backup_time_boundaries_do_not_overstate_recovery(flow, age, expected):
    original = flow[0].backup_listing
    def backup(**kwargs):
        result = original(**kwargs);result['archives'][0]['created_at'] = int(NOW.timestamp())-age
        return result
    flow[0].backup_listing = backup
    result = report(flow)
    assert result['targets'][0]['backup']['status'] == expected
    assert result['checks_complete'] is (expected == 'recent_archive')


def test_missing_backup_and_partial_query_failure_are_preserved(flow):
    original = flow[0].backup_listing
    def backup(**kwargs):
        result = original(**kwargs);result['archives'] = [];return result
    flow[0].backup_listing = backup
    def migration(**kwargs): raise MaintenanceError('permission_denied', '선택 권한 필요', 403)
    flow[0].migration_review = migration
    result = report(flow)['targets'][0]
    assert result['backup']['status'] == 'missing' and result['migration']['status'] == 'blocked'
    def backup_failed(**kwargs): raise MaintenanceError('source_failed', '조회 실패')
    flow[0].backup_listing = backup_failed
    assert report(flow)['targets'][0]['backup']['status'] == 'unavailable'


@pytest.mark.parametrize('kind', ['migration','backup'])
def test_changed_identity_is_not_prepared(flow, kind):
    attribute = 'migration_review' if kind == 'migration' else 'backup_listing'
    original = getattr(flow[0], attribute)
    def other(**kwargs):
        result = original(**kwargs);result['target']['vmid'] = 40001;return result
    setattr(flow[0], attribute, other)
    assert report(flow)['targets'][0][kind]['status'] == 'unavailable'


@pytest.mark.parametrize('options', [{'node_id': '../node'}, {'destination_node': 'node1'}, {'check_limit': 21},
    {'check_limit': True}, {'backup_max_age_hours': 0}, {'backup_max_age_hours': 721}, {'backup_storage': 'bad/path'}])
def test_invalid_query_never_observes_targets(flow, options):
    with pytest.raises(MaintenanceError): report(flow, **options)
    assert not flow[2]


def test_failure_on_one_target_keeps_other_target_ready(flow):
    vm = flow[1]['vms'][0]
    flow[1]['vms'].append({**vm, 'vmid': 40001})
    original = flow[0].migration_review
    def review(**kwargs):
        if kwargs['vmid'] == 40000: raise MaintenanceError('unavailable', '첫 대상 조회 실패')
        return original(**kwargs)
    flow[0].migration_review = review
    result = report(flow)
    assert result['prepared_target_count'] == 1
    assert result['targets'][0]['migration']['status'] == 'unavailable'
    assert result['targets'][1]['preparation'] == 'ready_for_manual_migration'


def test_offline_node_and_missing_required_source_are_not_ready(flow):
    flow[1]['nodes'][0]['status'] = 'offline'
    assert report(flow)['status'] == 'unavailable' and not flow[2]
    flow[1]['nodes'][0]['status'] = 'online'
    flow[1]['availability']['sources'].pop('vm_config')
    assert report(flow)['status'] == 'unavailable' and not flow[2]
