import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from app.domains.proxmox.risk_overrides import OperationalRiskOverrideStore
from app.shared.platform_models import Base, OperationalRiskOverride


class OperationalRiskOverrideStoreTest(unittest.TestCase):
    def _store(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "platform_state.db"
        database_url = f"sqlite:///{db_path}"
        engine = create_engine(database_url, future=True)
        OperationalRiskOverride.__table__.create(bind=engine)
        return OperationalRiskOverrideStore(database_url=database_url)

    def test_upsert_lists_and_clears_active_override(self):
        store = self._store()

        saved = store.upsert_override(
            "vm:node-a/101:backup-recency",
            "acknowledged",
            reason="accepted for maintenance",
            expires_at=1_700_010_000,
            updated_at=1_700_000_000,
        )

        self.assertEqual(saved["risk_id"], "vm:node-a/101:backup-recency")
        self.assertEqual(saved["status"], "acknowledged")
        active = store.list_active_overrides(now=1_700_000_100)
        self.assertEqual(active["vm:node-a/101:backup-recency"]["reason"], "accepted for maintenance")

        cleared = store.clear_override("vm:node-a/101:backup-recency")
        self.assertEqual(cleared, {"risk_id": "vm:node-a/101:backup-recency", "cleared": True})
        self.assertEqual(store.list_active_overrides(now=1_700_000_100), {})

    def test_expired_override_is_not_active(self):
        store = self._store()

        store.upsert_override(
            "vm:node-a/101:backup-recency",
            "suppressed",
            reason="expired exception",
            expires_at=1_700_000_000,
            updated_at=1_699_999_000,
        )

        self.assertEqual(store.list_active_overrides(now=1_700_000_001), {})

    def test_rejects_invalid_override_input(self):
        store = self._store()

        with self.assertRaises(ValueError):
            store.upsert_override("", "acknowledged")
        with self.assertRaises(ValueError):
            store.upsert_override("vm:node-a/101:backup-recency", "muted")

    def test_rejects_invalid_expiration_values(self):
        store = self._store()

        with self.assertRaises(ValueError):
            store.upsert_override(
                "vm:node-a/101:backup-recency",
                "suppressed",
                expires_at=float("inf"),
                updated_at=1_700_000_000,
            )
        with self.assertRaises(ValueError):
            store.upsert_override(
                "vm:node-a/101:backup-recency",
                "suppressed",
                expires_at=True,
                updated_at=1_700_000_000,
            )
        with self.assertRaises(ValueError):
            store.upsert_override(
                "vm:node-a/101:backup-recency",
                "suppressed",
                expires_at=1_699_999_999,
                updated_at=1_700_000_000,
            )


if __name__ == "__main__":
    unittest.main()
