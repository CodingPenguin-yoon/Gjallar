import pytest
from urllib.parse import parse_qs, urlsplit
from gjallar_client import cli, maintenance_workflow
from gjallar_client.errors import ClientError


class App:
    def __init__(self): self.calls=[]
    def request(self, path, **kwargs):
        self.calls.append((path,kwargs))
        query=parse_qs(urlsplit(path).query)
        return {'data': {'node_id':'node1','destination_node':query.get('destination_node',[None])[0],
            'backup_storage':query.get('backup_storage',[None])[0],
            'backup_max_age_hours':int(query['backup_max_age_hours'][0]),'check_limit':int(query['check_limit'][0]),
            'read_only':True,'node_shutdown_safe':False,'checks_complete':False}}


def test_maintenance_get_only_and_optional_fields():
    app=App()
    result=maintenance_workflow.show(app,node='node1')
    assert result['data']['node_shutdown_safe'] is False
    assert app.calls==[('maintenance/nodes/node1?backup_max_age_hours=24&check_limit=10',{'operator':True})]
    maintenance_workflow.show(app,node='node1',destination='node2',backup_storage='nfs',check_limit=2)
    assert 'destination_node=node2&backup_storage=nfs' in app.calls[-1][0]
    assert all(call[1]=={'operator':True} for call in app.calls)


@pytest.mark.parametrize('patch',[{'destination':'node1'},{'node':'../node'},{'check_limit':21},{'check_limit':True},
    {'backup_max_age_hours':0},{'backup_storage':'nfs/path'}])
def test_invalid_maintenance_input_has_no_request(patch):
    app=App()
    with pytest.raises(ClientError): maintenance_workflow.show(app,**{'node':'node1',**patch})
    assert not app.calls


@pytest.mark.parametrize('patch',[{'node_id':'other'},{'destination_node':'other'},{'backup_storage':'other'},
    {'check_limit':20},{'read_only':False},{'node_shutdown_safe':True}])
def test_wrong_report_is_not_accepted(patch):
    app=App();request=app.request
    def bad(*args,**kwargs):
        result=request(*args,**kwargs);result['data'].update(patch);return result
    app.request=bad
    with pytest.raises(ClientError) as error: maintenance_workflow.show(app,node='node1')
    assert error.value.code=='MAINTENANCE_REPORT_UNCONFIRMED'


def test_maintenance_parser():
    args=cli.parser().parse_args(['maintenance','node','node1','--destination','node2','--backup-storage','nfs','--check-limit','2'])
    assert args.node=='node1' and args.destination=='node2' and args.check_limit==2
