from copy import deepcopy
import pytest

from app.vm_actions import template_test
from app.vm_actions.post_create_readiness import PostCreateReadinessError, record_post_create_readiness_evidence
from test_post_create_readiness import _seed_succeeded_create_owner, _actor


@pytest.fixture
def report_source(monkeypatch):
    result = {'operation': {'operation_id': 'create-test', 'operation_type': 'vm_create', 'execution_mode': 'managed_api',
        'status': 'succeeded', 'target_type': 'proxmox_vm', 'target_id': 'vmid:40001',
        'details': {'target': {'node_id': 'node1', 'vmid': 40001, 'name': 'test'},
                    'template_source': {'node_id': 'node1', 'vmid': 40000}}},
        'create_readiness': {'readiness': {'power_policy': 'boot_and_verify', 'checks': {
            'running': True, 'cloud_init_completed': True, 'guest_agent_available': True, 'ip_observed': True}}}}
    monkeypatch.setattr(template_test, 'get_operation', lambda _: deepcopy(result))
    return result


def test_checks_distinguish_observation_from_access_and_current_state(report_source):
    report = template_test.template_test_report('create-test')
    assert [row['status'] for row in report['checks']] == ['passed'] * 4 + ['not_run']
    assert not report['all_checks_passed'] and report['historical'] and not report['live_checks_performed']
    assert 'SSH' in report['checks'][3]['limitation']
    assert report['cleanup']['automatic'] is False


@pytest.mark.parametrize('power,checks,status', [('stopped', {}, 'not_run'), ('boot_and_verify', {}, 'unavailable'),
                                             ('boot_and_verify', {'running': False}, 'not_verified')])
def test_absent_or_failed_checks_never_pass(report_source, power, checks, status):
    report_source['create_readiness']['readiness'].update(power_policy=power, checks=checks)
    assert template_test.template_test_report('create-test')['checks'][0]['status'] == status


@pytest.mark.parametrize('patch', [{'operation_type': 'vm_delete'}, {'target_id': 'vmid:40002'}, {'execution_mode': 'manual'}])
def test_report_rejects_wrong_operation_target(report_source, patch):
    report_source['operation'].update(patch)
    with pytest.raises(PostCreateReadinessError): template_test.template_test_report('create-test')


def test_unconfirmed_coordination_cannot_accept_access(report_source):
    report_source['coordination_incomplete'] = True
    assert not template_test.template_test_report('create-test')['can_record_access']


def test_real_evidence_record_is_exactly_linked_and_replay_preserved(report_source):
    _seed_succeeded_create_owner(operation_id='create-test', node_id='node1', vmid=40001)
    payload = {'create_operation_id': 'create-test', 'idempotency_key': 'access-one',
               'post_create_readiness_evidence_acknowledged': True,
               'checks': [{'name': 'access', 'status': 'passed', 'observed_at': '2026-09-19T00:00:00Z'}]}
    result = record_post_create_readiness_evidence(node_id='node1', vmid=40001, payload=payload, actor=_actor())
    report_source['operation']['details']['post_create_readiness_evidence'] = result['operation']['details']['post_create_readiness_evidence']
    report = template_test.template_test_report('create-test')
    assert report['all_checks_passed'] and report['checks'][-1]['actor']['username'] == 'operator'
    record_post_create_readiness_evidence(node_id='node1', vmid=40001,
        payload={**payload, 'checks': [{'name': 'access', 'status': 'failed'}]}, actor=_actor())
    assert template_test.template_test_report('create-test')['checks'][-1]['status'] == 'passed'
    report_source['operation']['details']['post_create_readiness_evidence']['artifact']['checksum'] = 'wrong'
    with pytest.raises(PostCreateReadinessError): template_test.template_test_report('create-test')


def test_source_identity_is_recorded_without_access_material():
    from app.operations.vm_create.application import VmCreateOperationTracker
    from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
    from app.operations.vm_create.domain import VmCreateOperationPlan
    from app.operations.core.domain import OperationActor
    plan = VmCreateOperationPlan('create-template-source', 'draft', 'node1', 40001, 'test', '', 'artifact',
        'sha256:' + 'a' * 64, 'yellow', {'power_policy': 'boot_and_verify',
        'review_confirm': {'template_node_id': 'node1', 'template_vmid': 40000, 'access': {'private': 'never-copy'}}}, OperationActor())
    operation = VmCreateOperationTracker(operations=SqlAlchemyOperationStore()).prepare(plan).operation
    assert operation.details['template_source'] == {'node_id': 'node1', 'vmid': 40000}
    assert operation.details['power_policy'] == 'boot_and_verify'
    assert 'never-copy' not in repr(operation.details)
