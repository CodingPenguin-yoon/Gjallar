import getpass
import json
import warnings

import pytest

from gjallar_client import cli
from gjallar_client.errors import ClientError


@pytest.mark.parametrize('command', ['login', 'connect', 'status', 'vms', 'vm', 'tui', 'shell', 'proxmox-setup', 'metrics', 'operations'])
def test_removed_commands_fail_before_opening_installation(command, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'Bootstrap', lambda *_: pytest.fail('removed command must not touch installation'))
    assert cli.main([command, '--json']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['error']['code'] == 'INVALID_ARGUMENT'
    assert '웹' in result['error']['message']


def test_help_does_not_open_installation(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'Bootstrap', lambda *_: pytest.fail('help must not touch installation'))
    assert cli.main([]) == 0
    assert '{bootstrap,service,upgrade}' in capsys.readouterr().out


@pytest.mark.parametrize('bind_address', ['127.0.0.1', '0.0.0.0'])
def test_bootstrap_only_installs_and_reports_web(tmp_path, monkeypatch, capsys, bind_address):
    options = {}
    def install(self, **kwargs):
        options.update(kwargs)
        return {'ok': True, 'state': 'running', 'url': 'http://127.0.0.1:8123', 'bind_address': bind_address}
    monkeypatch.setattr(cli.Bootstrap, 'install', install)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    assert cli.main(['bootstrap', '--install-dir', str(tmp_path / 'install'), '--port', '8123',
                     '--image', 'gjallar:test', '--bind-address', bind_address, '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert '브라우저' in result['next'] and 'login --connection' not in result['next']
    assert result['url'] == 'http://127.0.0.1:8123'
    assert options == {'image': 'gjallar:test', 'port': 8123, 'administrator': cli.administrator, 'bind_address': bind_address}
    assert not (tmp_path / 'config').exists()


@pytest.mark.parametrize('action', ['start', 'status', 'stop'])
def test_service_dispatch_preserves_installation_path(tmp_path, monkeypatch, capsys, action):
    calls = []
    def service(self, value):
        calls.append((self.directory, value))
        return {'ok': True, 'state': value}
    monkeypatch.setattr(cli.Bootstrap, 'service', service)
    assert cli.main(['--json', 'service', action, '--install-dir', str(tmp_path)]) == 0
    assert calls == [(tmp_path, action)]
    assert json.loads(capsys.readouterr().out)['state'] == action


def test_upgrade_delegates_without_exposing_errors(tmp_path, monkeypatch, capsys):
    def upgrade(self, image):
        assert self.directory == tmp_path and image == 'gjallar:next'
        raise ClientError('SCHEMA_MISMATCH', '기존 설치를 보존합니다.')
    monkeypatch.setattr(cli.Bootstrap, 'upgrade', upgrade)
    assert cli.main(['upgrade', '--image', 'gjallar:next', '--install-dir', str(tmp_path), '--json']) == 7
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'SCHEMA_MISMATCH'


def test_administrator_confirmation_and_secure_input(monkeypatch):
    answers = iter(['test-secret', 'test-secret'])
    assert cli.administrator(lambda _: 'admin', lambda _: next(answers)) == {'username': 'admin', 'password': 'test-secret'}
    with pytest.raises(ClientError, match='비밀번호'):
        cli.administrator(lambda _: 'admin', lambda _: '')
    def unmasked(_):
        warnings.warn('no terminal', getpass.GetPassWarning)
        pytest.fail('must fail before reading an unmasked password')
    monkeypatch.setattr(cli.getpass, 'getpass', unmasked)
    with pytest.raises(ClientError) as error:
        cli.secure_password('password: ')
    assert error.value.code == 'SECURE_INPUT_REQUIRED'


def test_human_output_escapes_terminal_controls(capsys):
    cli.emit({'state': 'bad\x1b[2J\u202e'}, as_json=False, stream=cli.sys.stdout)
    output = capsys.readouterr().out
    assert '\x1b' not in output and '\u202e' not in output
