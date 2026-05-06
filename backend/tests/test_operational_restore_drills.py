import tempfile
import unittest
from pathlib import Path

from app.domains.proxmox.restore_drills import OperationalRestoreDrillStore
from app.shared.platform_db import Base, create_platform_engine


class OperationalRestoreDrillStoreTest(unittest.TestCase):
    def _store(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "restore-drills.db"
        database_url = f"sqlite+pysqlite:///{db_path}"
        engine = create_platform_engine(database_url)
        Base.metadata.create_all(engine)
        return OperationalRestoreDrillStore(database_url=database_url)

    def test_record_list_and_latest_successful_drill_by_vmid(self):
        store = self._store()
        failed = store.record_drill(
            {
                "node": "node-a",
                "vmid": 401,
                "vm_name": "app-401",
                "datastore": "pbs-store",
                "snapshot": "vm/401/2026-01-01T00:00:00Z",
                "outcome": "failed",
                "drilled_at": 1_700_000_000,
                "recorded_at": 1_700_000_100,
                "recorded_by": "operator",
                "notes": "network validation failed",
                "evidence": {"ticket": "DRILL-1"},
            }
        )
        passed = store.record_drill(
            {
                "node": "node-a",
                "vmid": 401,
                "vm_name": "app-401",
                "datastore": "pbs-store",
                "snapshot": "vm/401/2026-02-01T00:00:00Z",
                "outcome": "passed",
                "drilled_at": 1_700_086_400,
                "recorded_at": 1_700_086_500,
                "recorded_by": "operator",
                "notes": "manual restore drill passed",
                "evidence": {"ticket": "DRILL-2"},
            }
        )

        self.assertNotEqual(failed["drill_id"], passed["drill_id"])
        records = store.list_drills(node="node-a", vmid=401)
        self.assertEqual([record["outcome"] for record in records], ["passed", "failed"])
        latest_success = store.get_latest_successful_drill_by_vmid(401)
        self.assertEqual(latest_success["drill_id"], passed["drill_id"])
        self.assertEqual(latest_success["outcome"], "passed")
        evidence = store.get_latest_restore_drill_evidence_by_vm(
            [{"node": "node-a", "vmid": 401}],
            now_epoch=1_700_172_800,
        )
        self.assertEqual(set(evidence), {"node-a/401"})
        self.assertEqual(evidence["node-a/401"]["outcome"], "passed")
        self.assertEqual(evidence["node-a/401"]["latest_drill_age_days"], 1.0)

    def test_invalid_restore_drill_outcome_is_rejected(self):
        store = self._store()

        with self.assertRaises(ValueError):
            store.record_drill(
                {
                    "node": "node-a",
                    "vmid": 402,
                    "outcome": "unknown",
                    "drilled_at": 1_700_000_000,
                }
            )

    def test_future_dated_restore_drill_timestamp_is_rejected(self):
        store = self._store()

        with self.assertRaises(ValueError):
            store.record_drill(
                {
                    "node": "node-a",
                    "vmid": 403,
                    "outcome": "passed",
                    "drilled_at": 1_700_000_100,
                    "recorded_at": 1_700_000_000,
                }
            )


if __name__ == "__main__":
    unittest.main()
