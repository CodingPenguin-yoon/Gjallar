import pytest
from gjallar_client import cli, metrics_workflow
from gjallar_client.errors import ClientError


class App:
    def __init__(self): self.calls = []
    def request(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return {'data': {'partial': True, 'history': {'available': False}}}


@pytest.mark.parametrize('kind,resource,suffix', [('node', None, ''), ('vm', 40000, '/vms/40000'), ('storage', 'store1', '/storage/store1')])
def test_metrics_returns_missing_evidence_without_mutation(kind, resource, suffix):
    app = App()
    result = metrics_workflow.show(app, kind=kind, node='node1', resource=resource, timeframe='year')
    assert result['data']['partial']
    assert app.calls == [('monitoring/nodes/node1'+suffix+'?timeframe=year', {})]


@pytest.mark.parametrize('kwargs', [{'kind': 'other'}, {'timeframe': 'decade'}, {'kind': 'vm', 'resource': True}, {'node': '../node'}])
def test_invalid_metrics_request_does_not_contact_server(kwargs):
    app = App()
    with pytest.raises(ClientError): metrics_workflow.show(app, **{'kind': 'node', 'node': 'node1', **kwargs})
    assert not app.calls


def test_metrics_parser():
    args = cli.parser().parse_args(['metrics', 'vm', '40000', '--node', 'node1', '--timeframe', 'day'])
    assert args.kind == 'vm' and args.resource == 40000 and args.node == 'node1'


def test_alerts_dispatch_is_read_only_and_limit_is_validated():
    app = App()
    cli.execute(cli.parser().parse_args(['alerts', '--limit', '50']), app)
    assert app.calls == [('monitoring/operation-alerts?limit=50', {})]
    for value in ('0', '51', 'bad'):
        with pytest.raises(ClientError): cli.parser().parse_args(['alerts', '--limit', value])
