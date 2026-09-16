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
