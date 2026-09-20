from pathlib import Path
import pytest
from alembic.command import upgrade, downgrade
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from app.db.session import reset_session_cache


def test_host_migration_preserves_vm_history_and_indexes_and_refuses_destructive_downgrade(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "host-migration.db"}'
    monkeypatch.setenv('GJALLAR_DATABASE_URL',url)
    reset_session_cache()
    config = Config(str(Path('backend/alembic.ini').resolve()))
    upgrade(config,'20260919_0041')
    engine = create_engine(url)
    insert = text('''insert into operation_locks
        (operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id, vmid, owner_id, reason, evidence, created_at, updated_at)
        values (:id, :kind, :scope, :key, :status, 'test', :vmid, :id, 'test', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''')
    def values(identity, **patch):
        return {'id':identity,'kind':'host_storage','scope':'proxmox_configuration','key':'config-test','status':'active','vmid':None,**patch}
    try:
        with engine.begin() as connection:
            connection.execute(insert,values('old-vm',kind='vm_compute',scope='proxmox_locator',key='vm-old',vmid=40000,status='released'))
        previous = {row['name'] for row in inspect(engine).get_indexes('operation_locks')}
        upgrade(config,'20260919_0042')
        assert {row['name'] for row in inspect(engine).get_indexes('operation_locks')} == previous | {'uq_operation_locks_open_configuration'}
        downgrade(config,'20260919_0041')
        upgrade(config,'20260919_0042')
        for patch in ({'vmid':40000},{'kind':'vm_compute'},{'scope':'proxmox_locator'}):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(insert,values('bad',**patch))
        with engine.begin() as connection: connection.execute(insert,values('host'))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert,values('host-race',kind='host_network',status='reconciliation_required'))
        with engine.begin() as connection:
            connection.execute(text("update operation_locks set status='released' where operation_lock_id='host'"))
            connection.execute(insert,values('next-host',kind='host_network'))
        with pytest.raises(RuntimeError,match='preserve records'): downgrade(config,'20260919_0041')
        with engine.connect() as connection:
            assert connection.execute(text('select count(*) from operation_locks')).scalar_one() == 3
            assert connection.execute(text("select vmid from operation_locks where operation_lock_id='old-vm'")).scalar_one() == 40000
            assert connection.execute(text('select version_num from alembic_version')).scalar_one() == '20260919_0042'
    finally:
        engine.dispose();reset_session_cache()
