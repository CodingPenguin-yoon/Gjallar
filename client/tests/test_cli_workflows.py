import json
from pathlib import Path

import httpx
import pytest

from gjallar_client import cli, workflows
from gjallar_client.api import Api
from gjallar_client.application import Application
from gjallar_client.connections import Connections
from gjallar_client.errors import ClientError
from gjallar_client.output import human
from gjallar_client.sessions import MemoryStore
from test_client import Server, TOKEN, PASSWORD


class WorkflowServer(Server):
    def __init__(self):
        super().__init__()
        self.timeout_mutation = False
        self.role = 'operator'
        self.status = 'succeeded'
        self.risk = 'yellow'
        self.node = 'pve'
        self.power_result_overrides = {}
        self.power_request = None

    def __call__(self, request):
        path = request.url.path
        if '/auth/' in path:
            response = super().__call__(request)
            payload = response.json()
            if 'user' in payload['data']:
                payload['data']['user']['role'] = self.role
            return httpx.Response(response.status_code, json=payload, headers=response.headers)
        self.calls.append(request)
        if path.endswith('/vms/101'):
            data = {'node_id': self.node, 'vmid': 101, 'name': 'app-01', 'status': 'stopped'}
        elif path.endswith('/drafts'):
            data = {'draft_id': 'draft-create-1'}
        elif path.endswith('/preflight'):
            data = {'risk_level': self.risk}
        elif path.endswith('/plan'):
            data = {'review_confirm': {'plan_artifact_id': 'plan-1', 'review_summary_checksum': 'checksum-1',
                                      'risk_summary': {'level': self.risk}, 'vmid': 101},
                    'risk_summary': {'level': self.risk}}
        elif path.endswith('/approve'):
            data = {'can_approve': self.risk != 'red'}
        elif path.endswith('/proxmox-preview'):
            # The real server declares that preview itself performs no mutation.
            data = {'proxmox_create_enabled': False, 'proxmox_mutation_enabled': False, 'approval': {'can_execute': True}}
        elif '/actions/' in path or path.endswith('/proxmox-create'):
            if self.timeout_mutation:
                raise httpx.ReadTimeout('synthetic hidden upstream body')
            if path.endswith(('/actions/start', '/actions/shutdown')):
                self.power_request = json.loads(request.content)
                self.power_action = path.rsplit('/', 1)[-1]
                # Existing native power endpoints expose canonical identity as job_id.
                data = {'job_id': 'power-1', 'status': 'completed'}
            else:
                data = {'operation': {'operation_id': 'create-1', 'status': self.status}}
        elif path.endswith('/operations/power-1'):
            data = {'operation': {'operation_id': 'power-1', 'status': self.status,
                    'operation_type': 'vm_' + self.power_action, 'target_type': 'proxmox_vm',
                    'target_id': 'vmid:101', 'idempotency_key': self.power_request['idempotency_key'],
                    'details': {'target': {'node_id': self.node, 'vmid': 101}},
                    **self.power_result_overrides}, 'coordination_incomplete': False}
        elif '/operations/' in path:
            data = {'operation': {'operation_id': 'create-1', 'status': self.status}, 'coordination_incomplete': False}
        else:
            data = []
        return httpx.Response(200, json={'ok': True, 'data': data})


@pytest.fixture
def environment(tmp_path):
    connections = Connections(tmp_path / 'config')
    connections.add('local', 'http://127.0.0.1:8000')
    server = WorkflowServer()
    store = MemoryStore()
    app = Application(connections, store, lambda p: Api(p, httpx.MockTransport(server)))
    app.login('operator', PASSWORD, 'local')
    return app, server, tmp_path


def prepare(environment):
    app, server, directory = environment
    spec = directory / 'spec.json'
    spec.write_text(json.dumps(workflows.EXAMPLE))
    review = directory / 'review.json'
    result = workflows.create_plan(app, spec, 'create-1', review)
    return result, review


def test_plan_and_execute_carry_exact_binding_without_mutation_during_plan(environment):
    app, server, _ = environment
    result, review = prepare(environment)
    assert result['exit_code'] == 0
    assert review.stat().st_mode & 0o777 == 0o600
    assert not any(r.url.path.endswith('/proxmox-create') for r in server.calls)
    confirmed = []
    result = workflows.create_execute(app, review, True, confirmed.append)
    assert result['exit_code'] == 0 and confirmed
    body = json.loads(next(r.content for r in reversed(server.calls) if r.method == 'POST'))
    assert body['plan_artifact_id'] == 'plan-1'
    assert body['review_summary_checksum'] == 'checksum-1'
    assert body['job_id'] == 'create-1'
    assert body['proxmox_mutation_acknowledged'] is True


def test_missing_yellow_ack_and_wrong_connection_never_approve(environment):
    app, server, _ = environment
    _, review = prepare(environment)
    count = len(server.calls)
    with pytest.raises(ClientError, match='yellow'):
        workflows.create_execute(app, review, False, lambda _: None)
    assert len(server.calls) == count
    app.connections.add('other', 'https://other.test')
    app.connection_name = 'other'
    with pytest.raises(ClientError) as error:
        workflows.create_execute(app, review, True, lambda _: None)
    assert error.value.code == 'REVIEW_CONNECTION_MISMATCH'
    assert len(server.calls) == count


def test_existing_review_not_overwritten_or_server_called(environment):
    app, server, _ = environment
    _, review = prepare(environment)
    original, count = review.read_bytes(), len(server.calls)
    with pytest.raises(ClientError):
        workflows.create_plan(app, review.parent / 'spec.json', 'create-1', review)
    assert review.read_bytes() == original and len(server.calls) == count


def test_red_plan_blocks_execute(environment):
    app, server, _ = environment
    server.risk = 'red'
    result, review = prepare(environment)
    assert result['exit_code'] == 8
    with pytest.raises(ClientError) as error:
        workflows.create_execute(app, review, True, lambda _: None)
    assert error.value.code == 'PLAN_BLOCKED'


@pytest.mark.parametrize('action', ['start', 'shutdown'])
def test_power_uses_target_binding_and_same_request_identity(environment, action):
    app, server, _ = environment
    result = workflows.power(app, action, 101, 'pve', 'request-1', lambda _: None)
    assert result['exit_code'] == 0
    body = json.loads(next(r.content for r in reversed(server.calls) if r.method == 'POST'))
    assert body['expected_name'] == 'app-01'
    assert body['idempotency_key'] == 'request-1'
    assert body[f'vm_{action}_acknowledged'] is True
    assert body['expected_status'] == ('stopped' if action == 'start' else 'running')


def test_wrong_node_and_viewer_never_mutate(environment):
    app, server, _ = environment
    with pytest.raises(ClientError) as error:
        workflows.power(app, 'start', 101, 'other', 'request-1', lambda _: None)
    assert error.value.code == 'TARGET_CHANGED'
    server.role = 'viewer'
    with pytest.raises(ClientError) as error:
        workflows.power(app, 'start', 101, 'pve', 'request-1', lambda _: None)
    assert error.value.exit_code == 4
    assert not any('/actions/' in r.url.path for r in server.calls)


@pytest.mark.parametrize('change', [
    {'operation_id': 'other'}, {'operation_type': 'vm_delete'}, {'target_id': 'vmid:102'},
    {'details': {'target': {'node_id': 'other', 'vmid': 101}}}, {'idempotency_key': 'other'},
])
def test_native_power_job_identity_must_match_canonical_operation(environment, change):
    app, server, _ = environment
    server.power_result_overrides = change
    with pytest.raises(ClientError) as error:
        workflows.power(app, 'start', 101, 'pve', 'request-1', lambda _: None)
    assert error.value.code == 'MUTATION_UNCONFIRMED'
    assert sum('/actions/' in r.url.path for r in server.calls) == 1


def test_timeout_is_not_retried_or_reported_as_success(environment):
    app, server, _ = environment
    server.timeout_mutation = True
    with pytest.raises(ClientError) as error:
        workflows.power(app, 'start', 101, 'pve', 'request-1', lambda _: None)
    assert error.value.code == 'MUTATION_UNCONFIRMED' and error.value.exit_code == 8
    assert sum('/actions/' in r.url.path for r in server.calls) == 1
    assert 'operations list' in str(error.value)


@pytest.mark.parametrize('status', ['running', 'failed', 'needs_reconciliation', 'blocked'])
def test_non_successful_operation_is_nonzero(environment, status):
    app, server, _ = environment
    server.status = status
    assert workflows.power(app, 'start', 101, 'pve', 'request-1', lambda _: None)['exit_code'] == 8


def test_common_flags_after_subcommands_and_json_errors(tmp_path, capsys):
    assert cli.main(['connection', 'list', '--config-dir', str(tmp_path/'config'), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['connections'] == {}
    assert cli.main(['vm', 'start', 'abc', '--json']) == 2
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'INVALID_ARGUMENT'
    args = cli.parser().parse_args(['--connection','one','vm','show','101','--json'])
    assert args.connection == 'one' and args.json


def test_default_help_does_not_open_tui_or_keyring(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'KeyringStore', lambda: pytest.fail('must not initialize keyring'))
    assert cli.main([]) == 0
    assert 'connect' in capsys.readouterr().out


def test_single_saved_connection_login_and_human_error(environment, monkeypatch, capsys):
    app, server, _ = environment
    app.connections.update(lambda data: data.update(selected=None))
    assert cli.login_name(app.connections, None) == 'local'
    monkeypatch.setattr(cli, 'Application', lambda *args, **kwargs: app)
    monkeypatch.setattr(cli, 'secure_password', lambda _: PASSWORD)
    assert cli.main(['login','--username','operator','--config-dir',str(app.connections.directory),'--human'], session_store=app.sessions) == 0
    printed = capsys.readouterr().out
    assert '계정' in printed and PASSWORD not in printed and TOKEN not in printed


def test_human_output_cannot_execute_terminal_sequences():
    result = {'data':[{'name':'bad\x1b[2J\u202e', 'vmid':101}], 'warning':'관찰 일부 누락'}
    output = human(result)
    assert '\x1b' not in output and '\u202e' not in output and '관찰 일부 누락' in output


def test_unconfirmed_noninteractive_power_does_not_dispatch(environment, monkeypatch):
    app, server, _ = environment
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: False)
    with pytest.raises(ClientError) as error:
        workflows.power(app,'start',101,'pve','request-1',lambda value: cli.confirm_change(value,False))
    assert error.value.code == 'CONFIRMATION_REQUIRED'
    assert not any('/actions/' in r.url.path for r in server.calls)


def test_bootstrap_reports_install_success_without_login(tmp_path, monkeypatch, capsys):
    from gjallar_client.bootstrap import Bootstrap
    monkeypatch.setattr(Bootstrap, 'install', lambda *args, **kwargs: {'ok': True, 'state': 'running', 'url': 'http://127.0.0.1:8000'})
    monkeypatch.setattr(cli, 'KeyringStore', lambda: pytest.fail('bootstrap must not require keyring'))
    assert cli.main(['bootstrap','--config-dir',str(tmp_path/'config'),'--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'running' and 'login --connection local-8000' in result['next']
    assert Connections(tmp_path/'config').read()['selected'] is None


def test_memory_shell_keeps_session_between_commands(tmp_path, monkeypatch, capsys):
    server = WorkflowServer()
    config = Connections(tmp_path / 'config')
    config.add('local', 'http://127.0.0.1:8000')
    monkeypatch.setattr(cli, 'Application', lambda connections, sessions, **kwargs:
                        Application(connections, sessions, lambda p: Api(p, httpx.MockTransport(server)), **kwargs))
    commands = iter(['login --username operator', 'status', 'vms', 'exit'])
    monkeypatch.setattr(cli, 'prompt', lambda _: next(commands))
    monkeypatch.setattr(cli, 'secure_password', lambda _: PASSWORD)
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    assert cli.main(['--config-dir',str(config.directory),'--session-mode','memory','shell']) == 0
    output = capsys.readouterr()
    results = [json.loads(line) for line in output.out.splitlines()]
    assert len(results) == 3 and all(item['ok'] for item in results)
    assert all(TOKEN in r.headers.get('cookie','') for r in server.calls if r.url.path.endswith('/me'))
    assert PASSWORD not in output.out + output.err and TOKEN not in output.out + output.err


def test_succeeded_with_incomplete_coordination_is_not_complete():
    result = workflows.result_status({'data':{'operation':{'operation_id':'op-1','status':'succeeded'},'coordination_incomplete':True}})
    assert result['exit_code'] == 8


@pytest.mark.parametrize('change', [{'creation_mode': []}, {'power_policy': []}, {'access': {'password':'secret'}}])
def test_invalid_spec_rejected_without_raw_values(change):
    with pytest.raises(ClientError) as error:
        workflows.validate_spec({**workflows.EXAMPLE, **change})
    assert error.value.exit_code == 2 and 'secret' not in str(error.value)


def test_followup_session_failure_preserves_uncertain_mutation(environment, monkeypatch):
    app, server, _ = environment
    original = app.request
    def request(path, **kwargs):
        if path.startswith('operations/'):
            raise ClientError('SESSION_EXPIRED', '로그인 필요', 3)
        return original(path, **kwargs)
    monkeypatch.setattr(app, 'request', request)
    with pytest.raises(ClientError) as error:
        workflows.power(app, 'start', 101, 'pve', 'request-1', lambda _: None)
    assert error.value.code == 'MUTATION_UNCONFIRMED' and error.value.exit_code == 8
    assert sum('/actions/' in r.url.path for r in server.calls) == 1


def test_bootstrap_external_web_keeps_cli_loopback_profile(tmp_path, monkeypatch, capsys):
    from gjallar_client.bootstrap import Bootstrap
    options = {}
    def install(self, **kwargs):
        options.update(kwargs)
        return {'ok': True, 'state': 'running', 'url': 'http://127.0.0.1:8000', 'bind_address': '0.0.0.0'}
    monkeypatch.setattr(Bootstrap, 'install', install)
    assert cli.main(['bootstrap', '--config-dir', str(tmp_path/'config'), '--bind-address', '0.0.0.0', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['bind_address'] == '0.0.0.0'
    assert options['bind_address'] == '0.0.0.0'
    assert Connections(tmp_path/'config').read()['connections']['local-8000']['origin'] == 'http://127.0.0.1:8000'
