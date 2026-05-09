import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.domains.proxmox.risk import DEFAULT_THRESHOLDS
from app.domains.proxmox.router import OperationalRiskThresholdUpdateRequest
from app.domains.proxmox.risk_config import OperationalRiskThresholdStore, validate_risk_thresholds
from app.shared.platform_db import Base, create_platform_engine


class OperationalRiskThresholdStoreTest(unittest.TestCase):
    def test_returns_defaults_and_persists_partial_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "thresholds.db"
            database_url = f"sqlite+pysqlite:///{db_path}"
            engine = create_platform_engine(database_url)
            Base.metadata.create_all(engine)

            store = OperationalRiskThresholdStore(database_url=database_url)
            defaults = store.get_thresholds()
            self.assertEqual(defaults["thresholds"], DEFAULT_THRESHOLDS)
            self.assertEqual(defaults["source"], "default")

            updated = store.update_thresholds({"stopped_warning_days": 14, "stopped_critical_days": 45})
            self.assertEqual(updated["thresholds"]["stopped_warning_days"], 14.0)
            self.assertEqual(updated["thresholds"]["stopped_critical_days"], 45.0)
            self.assertEqual(updated["source"], "database")

            restarted = OperationalRiskThresholdStore(database_url=database_url)
            persisted = restarted.get_thresholds()
            self.assertEqual(persisted["thresholds"]["stopped_warning_days"], 14.0)
            self.assertEqual(persisted["thresholds"]["stopped_critical_days"], 45.0)
            self.assertEqual(persisted["thresholds"]["storage_warning_percent"], DEFAULT_THRESHOLDS["storage_warning_percent"])

    def test_validates_threshold_ranges_and_ordering(self):
        with self.assertRaises(ValueError):
            validate_risk_thresholds({"storage_warning_percent": 95, "storage_critical_percent": 90})
        with self.assertRaises(ValueError):
            validate_risk_thresholds({"stopped_warning_days": 120, "stopped_critical_days": 90})
        with self.assertRaises(ValueError):
            validate_risk_thresholds({"backup_warning_days": 0})

    def test_threshold_update_request_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            OperationalRiskThresholdUpdateRequest(thresholds={"storage_warning_percent": 95})


if __name__ == "__main__":
    unittest.main()
