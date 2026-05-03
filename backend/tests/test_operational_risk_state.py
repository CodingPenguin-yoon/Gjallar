import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from app.domains.proxmox.risk_state import OperationalRiskStateStore
from app.domains.proxmox.service import ProxmoxService
from app.shared.platform_db import Base, create_platform_engine


class OperationalRiskStateStoreTest(unittest.TestCase):

    def test_service_does_not_use_singleton_inventory_completeness_flag(self):
        service_source = Path(__file__).resolve().parents[1] / "app/domains/proxmox/service.py"

        self.assertNotIn("_last_vm_inventory_complete", service_source.read_text())


    def _row_for_resource(self, database_url, resource_key):
        engine = create_platform_engine(database_url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    select resource_key,
                           active,
                           missing_since_at,
                           first_seen_at,
                           status_since_at,
                           last_running_at,
                           lifecycle_generation
                    from operational_vm_state
                    where resource_key = :resource_key
                    """
                ),
                {"resource_key": resource_key},
            ).mappings().first()
            return dict(row) if row is not None else None

    def test_missing_vm_is_marked_inactive_and_excluded_from_current_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            store = OperationalRiskStateStore(database_url=database_url)
            first_seen = 1_700_000_000
            store.observe_vms(
                [
                    {"node": "node-a", "vmid": 101, "name": "keep", "status": "running"},
                    {"node": "node-a", "vmid": 102, "name": "deleted", "status": "stopped"},
                ],
                observed_at=first_seen,
            )

            history = store.observe_vms(
                [{"node": "node-a", "vmid": 101, "name": "keep", "status": "running"}],
                observed_at=first_seen + 60,
            )

            self.assertEqual(set(history), {"node-a/101"})
            missing_row = self._row_for_resource(database_url, "qemu:102")
            self.assertEqual(missing_row["active"], False)
            self.assertEqual(missing_row["missing_since_at"], first_seen + 60)




    def test_node_scoped_inventory_does_not_reconcile_cluster_wide_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            first_seen = 1_700_000_000
            store = OperationalRiskStateStore(database_url=database_url)
            store.observe_vms(
                [
                    {"node": "node-a", "vmid": 101, "name": "node-a-vm", "status": "stopped"},
                    {"node": "node-b", "vmid": 202, "name": "node-b-vm", "status": "stopped"},
                ],
                observed_at=first_seen,
            )

            service = ProxmoxService()
            service.vm_inventory_cache_ttl_seconds = 0
            service._risk_state_store = store

            def fake_make_request(endpoint, method="GET", params=None):
                if endpoint == "/nodes/node-a/qemu":
                    return {"data": [{"vmid": 101, "name": "node-a-vm", "status": "stopped"}]}
                if endpoint == "/nodes/node-a/qemu/101/config":
                    return {"data": {}}
                return {"data": []}

            service._make_request = fake_make_request

            node_vms = service.get_vms(node="node-a")
            self.assertEqual([vm["vmid"] for vm in node_vms], [101])
            service.get_vm_state_history(node_vms, now_epoch=first_seen + 60)

            other_node_row = self._row_for_resource(database_url, "qemu:202")
            self.assertEqual(other_node_row["active"], True)
            self.assertIsNone(other_node_row["missing_since_at"])

    def test_partial_non_empty_inventory_does_not_mark_omitted_node_vms_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            first_seen = 1_700_000_000
            store = OperationalRiskStateStore(database_url=database_url)
            store.observe_vms(
                [
                    {"node": "node-a", "vmid": 101, "name": "visible", "status": "stopped"},
                    {"node": "node-b", "vmid": 202, "name": "hidden-by-node-error", "status": "stopped"},
                ],
                observed_at=first_seen,
            )

            service = ProxmoxService()
            service.vm_inventory_cache_ttl_seconds = 0
            service._risk_state_store = store

            def fake_make_request(endpoint, method="GET", params=None):
                if endpoint == "/nodes":
                    return {"data": [{"node": "node-a"}, {"node": "node-b"}]}
                if endpoint == "/nodes/node-a/qemu":
                    return {"data": [{"vmid": 101, "name": "visible", "status": "stopped"}]}
                if endpoint == "/nodes/node-b/qemu":
                    return {"data": [], "error": "node inventory timeout"}
                if endpoint == "/nodes/node-a/qemu/101/config":
                    return {"data": {}}
                return {"data": []}

            service._make_request = fake_make_request

            partial_vms = service.get_vms()
            self.assertEqual([vm["vmid"] for vm in partial_vms], [101])
            service.get_vm_state_history(partial_vms, now_epoch=first_seen + 60)

            omitted_row = self._row_for_resource(database_url, "qemu:202")
            self.assertEqual(omitted_row["active"], True)
            self.assertIsNone(omitted_row["missing_since_at"])

    def test_empty_inventory_snapshot_can_purge_already_inactive_rows_without_marking_active_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            store = OperationalRiskStateStore(database_url=database_url)
            first_seen = 1_700_000_000
            store.observe_vms(
                [
                    {"node": "node-a", "vmid": 101, "name": "old", "status": "stopped"},
                    {"node": "node-a", "vmid": 202, "name": "keep", "status": "running"},
                ],
                observed_at=first_seen,
            )
            store.observe_vms(
                [{"node": "node-a", "vmid": 202, "name": "keep", "status": "running"}],
                observed_at=first_seen + 60,
            )

            history = store.observe_vms([], observed_at=first_seen + 31 * 86400)

            self.assertEqual(history, {})
            self.assertIsNone(self._row_for_resource(database_url, "qemu:101"))
            keep_row = self._row_for_resource(database_url, "qemu:202")
            self.assertEqual(keep_row["active"], True)
            self.assertIsNone(keep_row["missing_since_at"])

    def test_empty_inventory_snapshot_does_not_mark_all_rows_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            store = OperationalRiskStateStore(database_url=database_url)
            store.observe_vms(
                [{"node": "node-a", "vmid": 101, "name": "app", "status": "running"}],
                observed_at=1_700_000_000,
            )

            self.assertEqual(store.observe_vms([], observed_at=1_700_000_100), {})
            row = self._row_for_resource(database_url, "qemu:101")
            self.assertEqual(row["active"], True)
            self.assertIsNone(row["missing_since_at"])

    def test_reappearing_vmid_after_missing_gap_starts_new_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            store = OperationalRiskStateStore(database_url=database_url)
            first_seen = 1_700_000_000
            store.observe_vms(
                [{"node": "node-a", "vmid": 101, "name": "old-vm", "status": "stopped"}],
                observed_at=first_seen,
            )
            store.observe_vms(
                [{"node": "node-a", "vmid": 202, "name": "other", "status": "running"}],
                observed_at=first_seen + 60,
            )

            reappeared_at = first_seen + 40 * 86400
            history = store.observe_vms(
                [{"node": "node-a", "vmid": 101, "name": "new-vm", "status": "stopped"}],
                observed_at=reappeared_at,
            )

            vm_history = history["node-a/101"]
            self.assertEqual(vm_history["stopped_since"], reappeared_at)
            self.assertEqual(vm_history["stopped_days"], 0.0)
            self.assertEqual(vm_history["lifecycle_generation"], 2)

            row = self._row_for_resource(database_url, "qemu:101")
            self.assertEqual(row["active"], True)
            self.assertIsNone(row["missing_since_at"])
            self.assertEqual(row["first_seen_at"], reappeared_at)
            self.assertEqual(row["status_since_at"], reappeared_at)
            self.assertEqual(row["lifecycle_generation"], 2)

    def test_inactive_rows_older_than_retention_are_purged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            store = OperationalRiskStateStore(database_url=database_url)
            first_seen = 1_700_000_000
            store.observe_vms(
                [
                    {"node": "node-a", "vmid": 101, "name": "old", "status": "stopped"},
                    {"node": "node-a", "vmid": 202, "name": "keep", "status": "running"},
                ],
                observed_at=first_seen,
            )
            store.observe_vms(
                [{"node": "node-a", "vmid": 202, "name": "keep", "status": "running"}],
                observed_at=first_seen + 60,
            )

            store.observe_vms(
                [{"node": "node-a", "vmid": 202, "name": "keep", "status": "running"}],
                observed_at=first_seen + 31 * 86400,
            )

            self.assertIsNone(self._row_for_resource(database_url, "qemu:101"))
            self.assertIsNotNone(self._row_for_resource(database_url, "qemu:202"))

    def test_observe_vms_persists_status_since_across_store_restarts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            first_seen = 1_700_000_000
            store = OperationalRiskStateStore(database_url=database_url)
            first_history = store.observe_vms(
                [
                    {
                        "node": "node-a",
                        "vmid": 101,
                        "name": "old-stopped",
                        "status": "stopped",
                    }
                ],
                observed_at=first_seen,
            )

            self.assertEqual(first_history["node-a/101"]["stopped_since"], first_seen)
            self.assertEqual(first_history["node-a/101"]["stopped_days"], 0.0)

            restarted = OperationalRiskStateStore(database_url=database_url)
            later = first_seen + 31 * 86400
            second_history = restarted.observe_vms(
                [
                    {
                        "node": "node-a",
                        "vmid": 101,
                        "name": "old-stopped",
                        "status": "stopped",
                    }
                ],
                observed_at=later,
            )

            self.assertEqual(second_history["node-a/101"]["stopped_since"], first_seen)
            self.assertEqual(second_history["node-a/101"]["stopped_days"], 31.0)

    def test_status_change_resets_status_since_and_records_running_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "risk-state.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            store = OperationalRiskStateStore(database_url=database_url)
            store.observe_vms(
                [{"node": "node-a", "vmid": 101, "name": "app", "status": "stopped"}],
                observed_at=1_700_000_000,
            )
            running_history = store.observe_vms(
                [{"node": "node-a", "vmid": 101, "name": "app", "status": "running"}],
                observed_at=1_700_000_100,
            )

            self.assertIsNone(running_history["node-a/101"].get("stopped_since"))
            self.assertEqual(running_history["node-a/101"]["status_since"], 1_700_000_100)
            self.assertEqual(running_history["node-a/101"]["last_running_at"], 1_700_000_100)

            stopped_again = store.observe_vms(
                [{"node": "node-a", "vmid": 101, "name": "app", "status": "stopped"}],
                observed_at=1_700_000_200,
            )

            self.assertEqual(stopped_again["node-a/101"]["stopped_since"], 1_700_000_200)
            self.assertEqual(stopped_again["node-a/101"]["stopped_days"], 0.0)


if __name__ == "__main__":
    unittest.main()
