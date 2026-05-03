import tempfile
import unittest
from pathlib import Path

from app.domains.proxmox.risk_state import OperationalRiskStateStore
from app.shared.platform_db import Base, create_platform_engine


class OperationalRiskStateStoreTest(unittest.TestCase):
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
