from pathlib import Path

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.session import reset_session_cache


@pytest.mark.parametrize("previous,revision,action", [
    ("20260917_0030", "20260919_0031", "vm_compute"),
    ("20260919_0031", "20260919_0032", "vm_disk_resize"),
    ("20260919_0032", "20260919_0033", "vm_network"),
    ("20260919_0033", "20260919_0034", "vm_clone"),
    ("20260919_0034", "20260919_0035", "vm_delete"),
    ("20260919_0035", "20260919_0036", "vm_template"),
    ("20260919_0036", "20260919_0037", "vm_image_build"),
    ("20260919_0037", "20260919_0038", "vm_image_cleanup"),
    ("20260919_0038", "20260919_0039", "vm_backup"),
    ("20260919_0039", "20260919_0040", "vm_restore"),
    ("20260919_0040", "20260919_0041", "vm_migrate"),
])
def test_compute_upgrade_preserves_lock_and_downgrade_preserves_history(tmp_path, monkeypatch, previous, revision, action):
    url = f"sqlite:///{tmp_path / 'compute-migration.db'}"
    monkeypatch.setenv("GJALLAR_DATABASE_URL", url)
    reset_session_cache()
    config = Config(str(Path("backend/alembic.ini").resolve()))
    upgrade(config, previous)
    engine = create_engine(url)
    insert = text("""insert into operation_locks
        (operation_lock_id, operation_type, scope_type, scope_key, status, cluster_id,
         vmid, owner_id, reason, evidence, created_at, updated_at)
        values (:id, :action, 'proxmox_locator', :scope, 'released', 'test',
                :vmid, :id, 'test', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""")
    try:
        with engine.begin() as connection:
            connection.execute(insert, dict(id="old", action="vm_start", scope="test|40000", vmid=40000))
        def indexes():
            return [(row["name"], row["column_names"], row["unique"],
                     {key: str(value) for key, value in row["dialect_options"].items()})
                    for row in inspect(engine).get_indexes("operation_locks")]
        previous_indexes = indexes()
        upgrade(config, revision)
        assert indexes() == previous_indexes
        with engine.connect() as connection:
            assert connection.execute(text("select operation_type from operation_locks where operation_lock_id='old'")).scalar_one() == "vm_start"
        downgrade(config, previous)
        upgrade(config, revision)
        with engine.begin() as connection:
            connection.execute(insert, dict(id="compute", action=action, scope="test|40001", vmid=40001))
        with pytest.raises(RuntimeError, match="preserve records"):
            downgrade(config, previous)
        with engine.connect() as connection:
            assert connection.execute(text("select count(*) from operation_locks")).scalar_one() == 2
            assert connection.execute(text("select version_num from alembic_version")).scalar_one() == revision
    finally:
        engine.dispose()
        reset_session_cache()
