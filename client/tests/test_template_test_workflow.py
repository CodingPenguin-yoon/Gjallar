from copy import deepcopy
import pytest
from gjallar_client import cli, template_test_workflow
from gjallar_client.errors import ClientError


class App:
    def __init__(self):
        self.calls = []
        self.report = {'operation_id': 'create-test', 'can_record_access': True, 'historical': True, 'live_checks_performed': False, 'target': {'node_id': 'node1', 'vmid': 40001}}
        self.response_patch = {}
        self.next_report_patch = {}
        self.link = 'create-test'
    def request(self, path, **kwargs):
        self.calls.append((path, kwargs))
        if kwargs.get('method') == 'POST':
            body = kwargs['body']
            artifact = {'artifact_id': 'access-evidence', 'checksum': 'sha256:fixture'}
            self.report['checks'] = [{**deepcopy(body['checks'][0]), 'artifact': artifact}]
            response = {'operation': {'operation_id': self.link}, 'operation_linked': True,
                        'create_operation_id': body['create_operation_id'], 'target': deepcopy(self.report['target']),
                        'checks': deepcopy(body['checks']), 'artifact': artifact, **self.response_patch}
            self.report.update(self.next_report_patch)
            return {'data': response}
        return {'data': deepcopy(self.report)}


def test_read_record_read_uses_exact_create_target_and_no_secret_fields():
    app = App()
    result = template_test_workflow.record_access(app, 'create-test', status='failed', request_id='access-test', acknowledged=True)
    assert len(app.calls) == 3 and result['data'] == app.report
    path, request = app.calls[1]
    assert path == 'nodes/node1/vms/40001/post-create-readiness-evidence' and request['operator']
    assert request['body']['checks'][0]['status'] == 'failed'
    assert request['body']['create_operation_id'] == 'create-test'
    assert set(request['body']) == {'create_operation_id', 'idempotency_key', 'post_create_readiness_evidence_acknowledged', 'summary', 'limitations', 'checks'}


@pytest.mark.parametrize('status,ack', [('passed', False), ('passed', 1), ('maybe', True)])
def test_missing_ack_or_invalid_status_never_posts(status, ack):
    app = App()
    with pytest.raises(ClientError): template_test_workflow.record_access(app, 'create-test', status=status, request_id='access-test', acknowledged=ack)
    assert not app.calls


@pytest.mark.parametrize('patch', [{'can_record_access': False}, {'operation_id': 'other'}, {'target': {'node_id': 'node1', 'vmid': True}}])
def test_unverified_or_mismatched_report_never_posts(patch):
    app = App(); app.report.update(patch)
    with pytest.raises(ClientError): template_test_workflow.record_access(app, 'create-test', status='passed', request_id='access-test', acknowledged=True)
    assert len(app.calls) == 1


def test_link_failure_does_not_resubmit():
    app = App(); app.link = 'other'
    with pytest.raises(ClientError) as caught:
        template_test_workflow.record_access(app, 'create-test', status='passed', request_id='access-test', acknowledged=True)
    assert caught.value.code == 'EVIDENCE_LINK_UNCONFIRMED' and len(app.calls) == 2


def test_cli_commands():
    assert cli.parser().parse_args(['vm', 'template-test', 'show', 'create-test']).stage == 'show'
    args = cli.parser().parse_args(['vm', 'template-test', 'record-access', 'create-test', '--status', 'failed', '--request-id', 'access-test', '--ack-evidence'])
    assert args.ack_evidence and args.status == 'failed'


@pytest.mark.parametrize('patch', [{'operation_id': 'other'}, {'historical': False}, {'live_checks_performed': True},
                                 {'target': {'node_id': '../node', 'vmid': 40001}}])
def test_show_rejects_wrong_or_nonhistorical_report(patch):
    app = App(); app.report.update(patch)
    with pytest.raises(ClientError): template_test_workflow.show(app, 'create-test')
    assert len(app.calls) == 1


@pytest.mark.parametrize('patch', [{'operation_linked': False}, {'create_operation_id': 'other'},
    {'target': {'node_id': 'node1', 'vmid': 40002}}, {'artifact': {}},
    {'checks': [{'name': 'access', 'status': 'not_run'}]}])
def test_saved_evidence_must_match_target_and_check(patch):
    app = App(); app.response_patch = patch
    with pytest.raises(ClientError) as caught:
        template_test_workflow.record_access(app, 'create-test', status='passed', request_id='access-test', acknowledged=True)
    assert caught.value.code == 'EVIDENCE_LINK_UNCONFIRMED'
    assert len(app.calls) == 2 and sum(call[1].get('method') == 'POST' for call in app.calls) == 1


@pytest.mark.parametrize('patch', [{'operation_id': 'other'}, {'target': {'node_id': 'node2', 'vmid': 40001}},
    {'checks': []}, {'checks': [{'name': 'access', 'status': 'not_run'}]},
    {'checks': [{'name': 'access', 'status': 'passed', 'observed_at': 'old',
                 'artifact': {'artifact_id': 'other', 'checksum': 'sha256:fixture'}}]}])
def test_reloaded_report_must_include_saved_evidence(patch):
    app = App(); app.next_report_patch = patch
    with pytest.raises(ClientError):
        template_test_workflow.record_access(app, 'create-test', status='passed', request_id='access-test', acknowledged=True)
    assert len(app.calls) == 3 and sum(call[1].get('method') == 'POST' for call in app.calls) == 1


@pytest.mark.parametrize('status', ['passed', 'failed', 'not_run', 'unavailable'])
def test_each_honest_access_result_can_be_confirmed(status):
    app = App()
    result = template_test_workflow.record_access(app, 'create-test', status=status, request_id='access-test', acknowledged=True)
    assert result['data']['checks'][0]['status'] == status


@pytest.mark.parametrize('field,value', [('status', 'failed'), ('observed_at', 'old'),
                                         ('artifact_id', 'other'), ('checksum', 'other')])
def test_reloaded_evidence_requires_each_exact_field(field, value):
    app = App()
    original_request = app.request
    def request(path, **kwargs):
        result = original_request(path, **kwargs)
        if len(app.calls) == 3:
            check = result['data']['checks'][0]
            if field in {'artifact_id', 'checksum'}:
                check['artifact'][field] = value
            else:
                check[field] = value
        return result
    app.request = request
    with pytest.raises(ClientError) as caught:
        template_test_workflow.record_access(app, 'create-test', status='passed', request_id='access-test', acknowledged=True)
    assert caught.value.code == 'EVIDENCE_LINK_UNCONFIRMED'
    assert len(app.calls) == 3 and sum(call[1].get('method') == 'POST' for call in app.calls) == 1


def test_explicit_idempotent_replay_preserves_original_check_and_time():
    app = App()
    original = {'name': 'access', 'status': 'failed', 'observed_at': '2026-09-18T00:00:00Z'}
    app.response_patch = {'idempotent_replay': True, 'checks': [original]}
    app.next_report_patch = {'checks': [{**original, 'artifact': {'artifact_id': 'access-evidence', 'checksum': 'sha256:fixture'}}]}
    result = template_test_workflow.record_access(app, 'create-test', status='passed', request_id='access-test', acknowledged=True)
    assert result['idempotent_replay'] is True and result['data']['checks'][0]['status'] == 'failed'
    assert result['data']['checks'][0]['observed_at'] == original['observed_at']
    assert len(app.calls) == 3
