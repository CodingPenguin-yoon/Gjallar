"""Exercise action admission with real PostgreSQL locks and stubbed Proxmox calls."""

import importlib
import os
import threading
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.metadata import Base
from app.db.session import get_engine, get_session_factory, reset_session_cache
from app.jobs.runs import get_job_run_strict
from app.operations.core.infrastructure.repository import SqlAlchemyOperationStore
from app.operations.locks.infrastructure.repository import SqlAlchemyDurableTargetLockRepository
from app.operations.recovery.infrastructure.repository import SqlAlchemyRecoveryStore
from app.operations.vm_shutdown.errors import VmShutdownError
from app.operations.vm_start.errors import VmStartError


pytestmark = pytest.mark.postgresql


@pytest.mark.parametrize("same_key,late_completion,kinds", [
    (True, False, ("migrate", "migrate")), (False, False, ("migrate", "migrate")), (True, True, ("migrate", "migrate")),
    (False, False, ("compute", "migrate")), (False, False, ("backup", "migrate")), (False, False, ("delete", "migrate")),
    (True, False, ("backup", "backup")), (False, False, ("backup", "backup")), (True, True, ("backup", "backup")),
    (False, False, ("compute", "backup")), (False, False, ("delete", "backup")),
    (True, False, ("compute", "compute")), (False, False, ("compute", "compute")), (True, True, ("compute", "compute")),
    (True, False, ("disk", "disk")), (False, False, ("disk", "disk")), (True, True, ("disk", "disk")),
    (True, False, ("delete", "delete")), (False, False, ("delete", "delete")), (True, True, ("delete", "delete")),
    (False, False, ("compute", "delete")), (False, False, ("disk", "delete")), (False, False, ("network", "delete")),
    (True, False, ("template", "template")), (False, False, ("template", "template")), (True, True, ("template", "template")),
    (False, False, ("compute", "template")), (False, False, ("disk", "template")),
    (False, False, ("network", "template")), (False, False, ("delete", "template")),
    (False, False, ("compute", "disk")),
    (True, False, ("network", "network")), (False, False, ("network", "network")), (True, True, ("network", "network")),
    (False, False, ("compute", "network")), (False, False, ("disk", "network")),
])
def test_resource_atomic_admission_race(postgres_actions, monkeypatch, same_key, late_completion, kinds):
    from app.operations.vm_migrate.application import MigrateService
    from app.operations.vm_migrate.domain import MigrateRequest
    from app.operations.vm_backup.application import BackupService
    from app.operations.vm_backup.domain import BackupRequest
    from app.operations.vm_template.application import TemplateService
    from app.operations.vm_template.domain import TemplateRequest
    from app.operations.vm_delete.application import DeleteService
    from app.operations.vm_delete.domain import DeleteRequest
    from app.operations.vm_network.application import NetworkService
    from app.operations.vm_network.domain import NetworkRequest
    from app.operations.vm_compute.application import ComputeService
    from app.operations.vm_compute.domain import ComputeRequest
    from app.operations.vm_compute.infrastructure import ComputeAdmission
    from app.operations.locks.domain import DurableTargetLockBusy
    from app.operations.vm_admission import VmMutationAdmission
    from app.operations.vm_disk.application import DiskService
    from app.operations.vm_disk.domain import DiskRequest

    admitted = threading.Barrier(2)
    original_current = SqlAlchemyDurableTargetLockRepository.current
    local = threading.local()
    completed = threading.Event()

    def synchronized_current(repository, **kwargs):
        result = original_current(repository, **kwargs)
        if not getattr(local, "checked", False):
            local.checked = True
            admitted.wait(timeout=15)
            if late_completion and local.index == 1:
                assert completed.wait(timeout=15)
        return result

    monkeypatch.setattr(SqlAlchemyDurableTargetLockRepository, "current", synchronized_current)
    released = threading.Event()
    calls = []

    class Client:
        def __init__(self, kind):
            self.kind = kind

        def review(self, **kwargs):
            return {'node_id': 'node-pg', 'vmid': 40000, 'name': 'test-vm', 'review_digest': 'sha256:' + 'b' * 64,
                    'vm': {'config_fingerprint': 'stable', 'digest': 'a' * 40}, 'destination': {'node_id': 'node-dest'}}

        def observe(self, **kwargs):
            return {'node_id': 'node-dest', 'vm': {'config_fingerprint': 'stable', 'digest': 'c' * 40},
                    'destination': {'node_id': 'node-dest'}, 'source_location_absent': True}

        def check_permissions(self, **kwargs):
            pass

        def observe_deletion(self, **kwargs):
            return {"vmid_unused": True, "deleted_volumes": ["store1:40000/vm-40000-disk-0.qcow2"],
                    "remaining_volumes": [], "preserved_volumes": [], "preservation_unconfirmed": []}

        def read(self, **kwargs):
            if self.kind == "backup":
                return {"vmid": 40000, "name": "test-vm", "status": "stopped", "storage_id": "store1",
                        "review_digest": "sha256:" + "b" * 64, "config_fingerprint": "stable", "volumes": [],
                        "archives": [{"volume_id": "store1:backup/new", "operation_marker": calls[-1]["operation_id"]}] if calls and "operation_id" in calls[-1] else []}
            if self.kind == "template":
                return {"vmid": 40000, "name": "test-vm", "digest": "a" * 40, "resources_digest": "sha256:" + "b" * 64,
                        "status": "stopped", "template": bool(kwargs.get('converted')), "config_fingerprint": "sha256:" + "c" * 64,
                        "volumes": [{"slot": "scsi0", "volume_id": "store1:40000/" + ("base" if kwargs.get('converted') else "vm") + "-40000-disk-0.qcow2"}]}
            if self.kind == "delete":
                return {"vmid": 40000, "name": "test-vm", "digest": "a" * 40, "resources_digest": "sha256:" + "b" * 64,
                        "deleted_volumes": [{"volume_id": "store1:40000/vm-40000-disk-0.qcow2"}], "preserved_volumes": []}
            if self.kind == "disk":
                return {"name": "test-vm", "digest": "a" * 40, "storage_id": "store1",
                        "volume_id": "store1:40000/vm-40000-disk-0.qcow2", "size_bytes": (24 if calls else 20) * 1024 ** 3}
            if self.kind == "network":
                return ({"name": "test-vm", "digest": "a" * 40,
                         "net0": "virtio=02:00:00:00:00:01,bridge=" + ("vmbr1,tag=100" if calls else "vmbr0")},
                        {"status": "stopped"}, [], {"pending_changes": False, "interfaces": [
                            {"iface": "vmbr0", "type": "bridge", "active": 1},
                            {"iface": "vmbr1", "type": "bridge", "active": 1, "bridge_vlan_aware": 1}]})
            return ({"name": "test-vm", "cores": 4 if calls else 2,
                     "memory": 4096 if calls else 2048, "digest": "a" * 40},
                    {"status": "stopped"}, [])

        def apply(self, **kwargs):
            calls.append(kwargs)
            if not late_completion:
                assert released.wait(timeout=15)
            if self.kind == "migrate":
                return "UPID:node-pg:0001:0002:0003:qmigrate:40000:test@pve!gjallar:"
            if self.kind == "backup":
                return "UPID:node-pg:0001:0002:0003:vzdump:40000:test@pve!gjallar:"
            if self.kind == "template":
                return "UPID:node-pg:0001:0002:0003:qmtemplate:40000:test@pve!gjallar:"
            if self.kind == "delete":
                return "UPID:node-pg:0001:0002:0003:qmdestroy:40000:test@pve!gjallar:"
            if self.kind == "disk":
                return "UPID:node-pg:0001:0002:0003:resize:40000:test@pve!gjallar:"

        def task(self, *, heartbeat=None, **kwargs):
            if heartbeat:
                heartbeat()
            return {"status": "stopped", "exitstatus": "OK"}

    def execute(index):
        local.index = index
        kind = kinds[index]
        service_type = {"migrate": MigrateService, "backup": BackupService, "compute": ComputeService, "disk": DiskService, "network": NetworkService, "delete": DeleteService, "template": TemplateService}[kind]
        admission = ComputeAdmission() if kind == "compute" else VmMutationAdmission(recovery_kind=f"vm_{kind}_observation")
        service = service_type(client=Client(kind), admission=admission,
            operations=SqlAlchemyOperationStore(), recovery=SqlAlchemyRecoveryStore(), cluster_id=postgres_actions)
        common = dict(idempotency_key="same" if same_key else f"key-{index}", expected_digest="a" * 40, expected_name="test-vm")
        request = (MigrateRequest(idempotency_key=common['idempotency_key'], expected_name='test-vm', destination_node='node-dest',
                    expected_review_digest='sha256:'+'b'*64, confirmation='40000/test-vm/node-pg->node-dest', migration_acknowledged=True) if kind == 'migrate' else BackupRequest(idempotency_key=common['idempotency_key'], expected_name='test-vm', storage_id='store1',
                    expected_review_digest='sha256:'+'b'*64, confirmation='40000/test-vm', backup_acknowledged=True) if kind == 'backup' else TemplateRequest(**common, expected_resources_digest="sha256:" + "b" * 64,
                    confirmation="40000/test-vm", guest_prepared=True, conversion_acknowledged=True) if kind == "template" else DeleteRequest(**common, expected_resources_digest="sha256:" + "b" * 64,
                                 confirmation="40000/test-vm", delete_acknowledged=True) if kind == "delete" else
                   ComputeRequest(**common, cores=4, memory_mib=4096) if kind == "compute" else
                   DiskRequest(**common, expected_volume="store1:40000/vm-40000-disk-0.qcow2",
                               expected_size_bytes=20 * 1024 ** 3, size_gib=24) if kind == "disk" else
                   NetworkRequest(**common, expected_net0="virtio=02:00:00:00:00:01,bridge=vmbr0", bridge_id="vmbr1", vlan_tag=100))
        try:
            return service.execute(node_id="node-pg", vmid=40000, request=request, actor={})
        except DurableTargetLockBusy as exc:
            return exc
        finally:
            if index == 0:
                completed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute, index) for index in range(2)]
        try:
            done, pending = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            if not late_completion:
                assert len(done) == len(pending) == 1
                assert isinstance(next(iter(done)).result(), DurableTargetLockBusy)
        finally:
            released.set()
        results = [future.result(timeout=15) for future in futures]
    assert len(calls) == 1
    successes = [result for result in results if isinstance(result, dict)]
    assert len(successes) == (2 if late_completion else 1)
    assert successes[0]["status"] == "succeeded"
    if late_completion and same_key:
        assert successes[1]["idempotent_replay"] is True
    assert len(SqlAlchemyOperationStore().list()) == 1
    assert SqlAlchemyRecoveryStore().get(successes[0]["operation_id"]).status == "completed"
    local.checked = True
    assert original_current(SqlAlchemyDurableTargetLockRepository(), cluster_id=postgres_actions, vmid=40000) is None


@pytest.fixture
def postgres_actions(monkeypatch):
    configured = os.getenv("GJALLAR_POSTGRES_TEST_URL")
    if not configured:
        pytest.skip("GJALLAR_POSTGRES_TEST_URL is required")
    schema = f"action_admission_{uuid.uuid4().hex}"
    admin = create_engine(configured)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = make_url(configured).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("GJALLAR_DATABASE_URL", scoped_url.render_as_string(hide_password=False))
    monkeypatch.setenv("GJALLAR_CLUSTER_ID", schema)
    reset_session_cache()
    try:
        Base.metadata.create_all(get_engine())
        get_session_factory()
        yield schema
    finally:
        reset_session_cache()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


class Inventory:
    def __init__(self, action):
        self.status = "stopped" if action == "start" else "running"

    def list_vms(self):
        return [{"node_id": "node-pg", "vmid": 306, "name": "app", "status": self.status,
                 "template": False}]

    def list_templates(self):
        return []


class MutationClient:
    def __init__(self, action, calls, release=None):
        self.action = action
        self.calls = calls
        self.release = release

    def redacted_connection_context(self):
        return {"mode": "test"}

    def _mutate(self, node, vmid):
        self.calls.append((self.action, node, vmid))
        if self.release is not None:
            assert self.release.wait(timeout=15), "Concurrent request did not finish admission"
        return f"UPID:{node}:0001:qm{self.action}"

    def start_vm(self, *, node, vmid):
        return self._mutate(node, vmid)

    def shutdown_vm(self, *, node, vmid):
        return self._mutate(node, vmid)

    def wait_for_task(self, *, node, upid, heartbeat=None):
        if heartbeat is not None:
            heartbeat()
        return {"node": node, "upid": upid, "status": "stopped", "exitstatus": "OK"}

    def get_vm_status(self, *, node, vmid):
        return {"node_id": node, "vmid": vmid, "name": "app",
                "status": "running" if self.action == "start" else "stopped"}


def _execute(action, key, calls, release=None, expected_name="app"):
    module = importlib.import_module(f"app.vm_actions.{action}")
    try:
        return getattr(module, f"run_vm_{action}")(
            node_id="node-pg", vmid=306,
            payload={f"vm_{action}_acknowledged": True, "idempotency_key": key,
                     "expected_name": expected_name, "expected_status": Inventory(action).status},
            inventory_adapter=Inventory(action), client=MutationClient(action, calls, release),
        )
    except (VmStartError, VmShutdownError) as exc:
        return exc


def _synchronize_prepared_requests(monkeypatch):
    prepared = threading.Barrier(2)
    original_create = SqlAlchemyOperationStore.create

    def create(store, *args, **kwargs):
        result = original_create(store, *args, **kwargs)
        prepared.wait(timeout=15)
        return result

    monkeypatch.setattr(SqlAlchemyOperationStore, "create", create)


@pytest.mark.parametrize("actions,same_key", [
    (("start", "start"), True),
    (("shutdown", "shutdown"), True),
    (("start", "start"), False),
    (("shutdown", "shutdown"), False),
    (("start", "shutdown"), False),
])
def test_concurrent_actions_have_one_mutation_and_preserve_owner(
    monkeypatch, postgres_actions, actions, same_key,
):
    _synchronize_prepared_requests(monkeypatch)
    release = threading.Event()
    calls = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_execute, action, "same" if same_key else f"key-{index}", calls, release)
                   for index, action in enumerate(actions)]
        try:
            done, pending = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            assert len(done) == len(pending) == 1
            loser = next(iter(done)).result()
            if same_key and isinstance(loser, dict):
                assert loser["idempotent_replay"] is True
                assert loser["status"] == "running"
                assert loser["proxmox_mutation_enabled"] is False
            else:
                assert isinstance(loser, (VmStartError, VmShutdownError))
                assert loser.status_code == 409
                assert loser.code.endswith("_IN_PROGRESS" if same_key else "_TARGET_LOCK_BUSY")
            active = SqlAlchemyDurableTargetLockRepository().current(cluster_id=postgres_actions, vmid=306)
            assert active is not None
            owner = SqlAlchemyOperationStore().get(active.owner_id)
            assert owner.status in {"planned", "dispatching", "running"}
        finally:
            release.set()
        results = [future.result(timeout=15) for future in futures]

    successes = [result for result in results if isinstance(result, dict) and not result.get("idempotent_replay")]
    assert len(successes) == 1
    assert len(calls) == 1
    job_id = successes[0]["job_id"]
    assert get_job_run_strict(job_id)["status"] == "completed"
    assert SqlAlchemyOperationStore().get(job_id).status == "succeeded"
    assert SqlAlchemyRecoveryStore().get(job_id).status == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id=postgres_actions, vmid=306) is None


@pytest.mark.parametrize("action", ["start", "shutdown"])
def test_concurrent_conflicting_intents_keep_one_operation(monkeypatch, postgres_actions, action):
    preparing = threading.Barrier(2)
    original_create = SqlAlchemyOperationStore.create

    def create(store, *args, **kwargs):
        preparing.wait(timeout=15)
        return original_create(store, *args, **kwargs)

    monkeypatch.setattr(SqlAlchemyOperationStore, "create", create)
    calls = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_execute, action, "conflicting-intent", calls, expected_name=name)
                   for name in ("app", "")]
        results = [future.result(timeout=15) for future in futures]

    successes = [result for result in results if isinstance(result, dict)]
    errors = [result for result in results if isinstance(result, (VmStartError, VmShutdownError))]
    assert len(successes) == len(errors) == len(calls) == 1
    assert errors[0].status_code == 409
    assert errors[0].code == f"VM_{action.upper()}_IDEMPOTENCY_CONFLICT"
    job_id = successes[0]["job_id"]
    assert SqlAlchemyOperationStore().get(job_id).status == "succeeded"
    assert get_job_run_strict(job_id)["status"] == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id=postgres_actions, vmid=306) is None


@pytest.mark.parametrize("action", ["start", "shutdown"])
def test_late_lock_acquisition_replays_completed_projection(monkeypatch, postgres_actions, action):
    _synchronize_prepared_requests(monkeypatch)
    completed = threading.Event()
    local = threading.local()
    acquire = SqlAlchemyDurableTargetLockRepository.acquire

    def delayed_acquire(repository, **kwargs):
        if local.late:
            assert completed.wait(timeout=15)
        return acquire(repository, **kwargs)

    monkeypatch.setattr(SqlAlchemyDurableTargetLockRepository, "acquire", delayed_acquire)
    calls = []

    def execute(late):
        local.late = late
        try:
            return _execute(action, "late-completion", calls)
        finally:
            if not late:
                completed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, (False, True)))

    assert all(isinstance(result, dict) for result in results), results
    assert results[1]["idempotent_replay"] is True
    assert len(calls) == 1
    job_id = results[0]["job_id"]
    assert get_job_run_strict(job_id)["status"] == "completed"
    store = SqlAlchemyOperationStore()
    assert store.get(job_id).status == "succeeded"
    assert store.list_events(job_id)[-1].to_status == "succeeded"
    assert SqlAlchemyRecoveryStore().get(job_id).status == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id=postgres_actions, vmid=306) is None


@pytest.mark.parametrize("action", ["start", "shutdown"])
@pytest.mark.parametrize("interleaving", ["replay_completed", "replay_claimed", "foreground_completed"])
def test_no_effect_foreground_and_replay_close_without_orphaned_lease(
    monkeypatch, postgres_actions, action, interleaving,
):
    module = importlib.import_module(f"app.vm_actions.{action}")
    failure_published = threading.Event()
    replay_claimed = threading.Event()
    replay_preparing = threading.Event()
    replay_finished = threading.Event()
    foreground_finished = threading.Event()
    local = threading.local()
    record_job = module.record_job_run
    prepare = SqlAlchemyRecoveryStore.prepare_and_claim

    def record(**kwargs):
        result = record_job(**kwargs)
        if local.role == "foreground" and kwargs.get("status") == "failed":
            failure_published.set()
            gate = {
                "replay_completed": replay_finished,
                "replay_claimed": replay_claimed,
                "foreground_completed": replay_preparing,
            }[interleaving]
            assert gate.wait(timeout=15)
        return result

    def prepare_replay(store, *args, **kwargs):
        if local.role == "replay" and interleaving == "foreground_completed":
            replay_preparing.set()
            assert foreground_finished.wait(timeout=15)
        result = prepare(store, *args, **kwargs)
        if local.role == "replay" and interleaving == "replay_claimed":
            replay_claimed.set()
            assert foreground_finished.wait(timeout=15)
        return result

    monkeypatch.setattr(module, "record_job_run", record)
    monkeypatch.setattr(SqlAlchemyRecoveryStore, "prepare_and_claim", prepare_replay)

    def execute(role):
        local.role = role
        if role == "replay":
            assert failure_published.wait(timeout=15)
        try:
            return getattr(module, f"run_vm_{action}")(
                node_id="node-pg", vmid=306, inventory_adapter=Inventory(action),
                payload={f"vm_{action}_acknowledged": True, "idempotency_key": "no-client",
                         "expected_name": "app", "expected_status": Inventory(action).status},
            )
        except (VmStartError, VmShutdownError) as exc:
            return exc
        finally:
            (foreground_finished if role == "foreground" else replay_finished).set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, ("foreground", "replay")))

    assert isinstance(results[0], (VmStartError, VmShutdownError))
    assert results[0].code == f"VM_{action.upper()}_CLIENT_UNAVAILABLE"
    assert isinstance(results[1], dict), results[1]
    assert results[1]["idempotent_replay"] is True
    assert results[1]["status"] == "failed"
    job_id = results[1]["job_id"]
    assert SqlAlchemyOperationStore().get(job_id).status == "failed"
    assert get_job_run_strict(job_id)["status"] == "failed"
    recovery = SqlAlchemyRecoveryStore().get(job_id)
    assert recovery is None or recovery.status == "completed"
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id=postgres_actions, vmid=306) is None


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('operation_types', [('vm_clone','vm_clone'),('vm_restore','vm_restore'),('vm_clone','vm_restore')])
def test_multi_target_admission_serializes_both_targets_without_partial_locks(postgres_actions, monkeypatch, reverse, operation_types):
    from app.operations.core.domain import OperationActor, OperationSpec
    from app.operations.locks.domain import DurableTargetLockBusy
    from app.operations.vm_admission import VmMutationAdmission
    from app.db.models import OperationLockRecord
    from app.db.session import session_scope
    from sqlalchemy import select
    barrier = threading.Barrier(2)
    local = threading.local()
    current = SqlAlchemyDurableTargetLockRepository.current
    def synchronize(repository, **kwargs):
        result = current(repository, **kwargs)
        if not getattr(local, 'checked', False):
            local.checked = True
            barrier.wait(timeout=15)
        return result
    monkeypatch.setattr(SqlAlchemyDurableTargetLockRepository, 'current', synchronize)
    def execute(index):
        source, destination = (40001, 40000) if reverse and index else (40000, 40001)
        operation_type = operation_types[index]
        identity = f'{operation_type}-{index}'
        value = OperationSpec(operation_id=identity, operation_type=operation_type, execution_mode='managed_api',
            target_type='proxmox_vm', target_id=f'vmid:{destination}', idempotency_key=identity,
            intent_digest='sha256:' + str(index) * 64, plan_digest='sha256:' + str(index) * 64, actor=OperationActor(),
            details={'source': {'node_id': 'node-pg', 'vmid': source}, 'target': {'node_id': 'node-pg', 'vmid': destination}})
        try:
            return VmMutationAdmission(recovery_kind=operation_type + '_observation').prepare(value, cluster_id=postgres_actions,
                vmid=destination, related_vmids=(source,))
        except DurableTargetLockBusy as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, (0, 1)))
    accepted = [row for row in results if isinstance(row, tuple)]
    assert len(accepted) == 1
    assert len([row for row in results if isinstance(row, DurableTargetLockBusy)]) == 1
    operation, lease = accepted[0]
    monkeypatch.setattr(SqlAlchemyDurableTargetLockRepository, 'current', current)
    with session_scope() as session:
        locks = list(session.scalars(select(OperationLockRecord)))
        assert len(locks) == 2 and {row.owner_id for row in locks} == {operation.operation_id}
    SqlAlchemyRecoveryStore().commit_observation(lease, next_status='blocked', stage='precheck', event_type='test_no_effect',
        expected_statuses=['planned'], recovery_status='completed', release_target_lock=True)
    repository = SqlAlchemyDurableTargetLockRepository()
    assert all(repository.current(cluster_id=postgres_actions, vmid=vmid) is None for vmid in (40000, 40001))


@pytest.mark.parametrize('same_key', [False, True])
@pytest.mark.parametrize('operation_type', ['vm_image_build', 'vm_image_cleanup'])
def test_image_build_admission_and_stage_checkpoints_are_atomic(postgres_actions, monkeypatch, same_key, operation_type):
    from app.operations.core.domain import OperationActor, OperationSpec, operation_digest
    from app.operations.locks.domain import DurableTargetLockBusy
    from app.operations.vm_admission import VmMutationAdmission
    from app.operations.recovery.domain import RecoveryLease
    barrier = threading.Barrier(2)
    local = threading.local()
    current = SqlAlchemyDurableTargetLockRepository.current
    def synchronize(repository, **kwargs):
        result = current(repository, **kwargs)
        if not getattr(local, 'checked', False):
            local.checked = True
            barrier.wait(timeout=15)
        return result
    monkeypatch.setattr(SqlAlchemyDurableTargetLockRepository, 'current', synchronize)
    def admit(index):
        identity = 'image-build-' + str(0 if same_key else index)
        spec = OperationSpec(operation_id=identity, operation_type=operation_type, execution_mode='managed_api',
            target_type='proxmox_vm', target_id='vmid:40000', idempotency_key=identity,
            intent_digest=operation_digest({'identity': identity}), plan_digest=operation_digest({'identity': identity}), actor=OperationActor(),
            details={'target': {'node_id': 'node-pg', 'vmid': 40000}, 'mutation_dispatched': False})
        try:
            return VmMutationAdmission(recovery_kind=operation_type + '_observation').prepare(spec, cluster_id=postgres_actions, vmid=40000)
        except DurableTargetLockBusy as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, (0, 1)))
    owners = [value for value in results if isinstance(value, tuple) and value[1] is not None]
    assert len(owners) == 1
    assert len([value for value in results if isinstance(value, DurableTargetLockBusy)]) == 1
    assert len(SqlAlchemyOperationStore().list()) == 1
    monkeypatch.setattr(SqlAlchemyDurableTargetLockRepository, 'current', current)
    operation, lease = owners[0]
    store = SqlAlchemyRecoveryStore()
    for index, stage in enumerate(('upload', 'create', 'template')):
        patch = {'build_stage': stage, 'stage_dispatch_state': 'dispatching', 'mutation_dispatched': True}
        operation, item = store.commit_observation(lease, next_status='dispatching' if index == 0 else None,
            event_type='image_stage_checkpoint', stage=stage, details_patch=patch, recovery_details_patch=patch,
            expected_statuses=[operation.status], expected_operation_version=operation.version,
            expected_operation_checksum=operation.last_event_checksum, recovery_status='leased')
        lease = RecoveryLease(item=item, token=lease.token)
        assert store.get(operation.operation_id).details['build_stage'] == operation.details['build_stage'] == stage
    store.commit_observation(lease, next_status='needs_reconciliation', event_type='synthetic_interruption', stage='reconciliation',
        expected_statuses=['dispatching'], recovery_status='paused')
    assert SqlAlchemyDurableTargetLockRepository().current(cluster_id=postgres_actions, vmid=40000)


@pytest.mark.parametrize('second', ['vm_compute', 'host_network', 'same_host_request'])
def test_host_configuration_and_vm_admission_share_one_gate(postgres_actions, second):
    from app.operations.core.domain import OperationActor, OperationSpec
    from app.operations.host_config.admission import HostConfigurationAdmission
    from app.operations.host_config.domain import target_identity
    from app.operations.host_config.infrastructure import ConfigurationLockRepository
    from app.operations.locks.domain import DurableTargetLockBusy
    from app.db.models import OperationLockRecord
    from app.db.session import session_scope
    from sqlalchemy import select
    barrier = threading.Barrier(2)
    def admit(index):
        barrier.wait(timeout=15)
        try:
            if index == 1 and second == 'vm_compute':
                return SqlAlchemyDurableTargetLockRepository().acquire(operation_type='vm_compute', cluster_id=postgres_actions,
                    vmid=40000, owner_id='vm-race', reason='test')
            kind = 'host_network' if index and second == 'host_network' else 'host_storage'
            identity = 'host-' + str(0 if second == 'same_host_request' else index)
            target = {'node_id':'node-pg', **({'bridge_id':'vmbr9'} if kind == 'host_network' else {'storage_id':'new-dir'})}
            target_type, target_id = target_identity(kind,target)
            value = OperationSpec(operation_id=identity, operation_type=kind, execution_mode='managed_api', target_type=target_type,
                target_id=target_id, idempotency_key=identity, intent_digest='sha256:'+'a'*64, plan_digest='sha256:'+'a'*64,
                actor=OperationActor(), details={'target':target,'mutation_dispatched':False})
            return HostConfigurationAdmission().prepare(value,cluster_id=postgres_actions)
        except DurableTargetLockBusy as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit,(0,1)))
    with session_scope() as session:
        locks = list(session.scalars(select(OperationLockRecord)))
        assert len(locks) == 1
    if second == 'same_host_request':
        assert all(isinstance(result,tuple) for result in results)
        assert sum(result[1] is not None for result in results) == 1
        assert len(SqlAlchemyOperationStore().list()) == 1
    else:
        assert sum(isinstance(result,DurableTargetLockBusy) for result in results) == 1
    for result in results:
        if isinstance(result,tuple) and result[1] is not None:
            SqlAlchemyRecoveryStore().commit_observation(result[1],next_status='blocked',event_type='test_no_effect',stage='precheck',
                expected_statuses=['planned'],recovery_status='completed',release_target_lock=True)
            assert ConfigurationLockRepository().current(cluster_id=postgres_actions) is None
        elif not isinstance(result,(tuple,DurableTargetLockBusy)):
            assert SqlAlchemyDurableTargetLockRepository().release(result,reason='test_finished')
