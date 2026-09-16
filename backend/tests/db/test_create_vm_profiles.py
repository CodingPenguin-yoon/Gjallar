"""Tests for DB-backed Create VM profile seed and repository behavior."""

from __future__ import annotations

from app.db import create_vm_profiles as profile_repository

from datetime import datetime, timezone
import os
import tempfile
import unittest
from unittest.mock import patch

from app.db.create_vm_profiles import list_active_create_vm_profiles
from app.db.models import Base, CreateVmProfile
from app.db.seed_create_vm_profiles import seed_create_vm_profiles
from app.db.session import get_engine, reset_session_cache, session_scope


class CreateVmProfileDbTests(unittest.TestCase):
    def test_active_profiles_return_db_seed_source_without_forbidden_fields(self):
        profiles = list_active_create_vm_profiles()

        self.assertEqual(["general-vm", "runtime-server", "development-vm"], [profile.profile_id for profile in profiles])
        for profile in profiles:
            data = profile.to_dict()
            self.assertEqual("db_seed", data["source"])
            self.assertEqual("read_only", data["management"])
            self.assertEqual(set(), {"target_node_candidates", "template_family", "default_ip_mode"} & set(data))

    def test_seed_is_idempotent_and_does_not_overwrite_operator_changes(self):
        with session_scope() as session:
            general = session.get(CreateVmProfile, "general-vm")
            runtime = session.get(CreateVmProfile, "runtime-server")
            self.assertIsNotNone(general)
            self.assertIsNotNone(runtime)
            general.display_name = "Operator General"
            runtime.enabled = False
            runtime.disabled_at = datetime.now(timezone.utc)

        result = seed_create_vm_profiles()

        self.assertTrue(result.skipped)
        self.assertEqual(0, result.inserted)
        with session_scope() as session:
            self.assertEqual(3, session.query(CreateVmProfile).count())
            self.assertEqual("Operator General", session.get(CreateVmProfile, "general-vm").display_name)
            self.assertFalse(session.get(CreateVmProfile, "runtime-server").enabled)
            self.assertIsNotNone(session.get(CreateVmProfile, "runtime-server").disabled_at)

    def test_disabled_and_archived_profiles_are_excluded_from_active_reads(self):
        now = datetime.now(timezone.utc)
        with session_scope() as session:
            runtime = session.get(CreateVmProfile, "runtime-server")
            development = session.get(CreateVmProfile, "development-vm")
            runtime.disabled_at = now
            development.archived_at = now

        profiles = list_active_create_vm_profiles()

        self.assertEqual(["general-vm"], [profile.profile_id for profile in profiles])

    def test_seed_inserts_initial_profiles_when_table_is_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_url = f"sqlite:///{os.path.join(temp_dir, 'seed-test.db')}"
            with patch.dict(os.environ, {"GJALLAR_DATABASE_URL": database_url}, clear=False):
                reset_session_cache()
                Base.metadata.create_all(get_engine())

                result = seed_create_vm_profiles()

                self.assertFalse(result.skipped)
                self.assertEqual(3, result.inserted)
                self.assertEqual(
                    ["general-vm", "runtime-server", "development-vm"],
                    [profile.profile_id for profile in list_active_create_vm_profiles()],
                )
            reset_session_cache()

    def test_draft_defaults_read_profile_values_from_db(self):
        from app.vm_create.drafts import build_default_vm_draft

        with session_scope() as session:
            runtime = session.get(CreateVmProfile, "runtime-server")
            runtime.cpu_default = 6
            runtime.memory_mb_default = 12288
            runtime.disk_gb_default = 120

        draft = build_default_vm_draft(profiles=profile_repository.get_active_create_vm_profiles_by_id(), operator_id="db-profile-test", profile_id="runtime-server")

        self.assertEqual("runtime-server", draft.profile_id)
        self.assertEqual((6, 12288, 120), (draft.hardware.cpu, draft.hardware.memory_mb, draft.hardware.disk_gb))

    def test_preflight_uses_db_profile_limits(self):
        from app.proxmox.inventory import FakeProxmoxInventoryAdapter
        from app.vm_create.drafts import build_default_vm_draft
        from app.vm_create.preflight import run_preflight

        draft = build_default_vm_draft(
            profiles=profile_repository.get_active_create_vm_profiles_by_id(),
            operator_id="db-preflight-test",
            target_node_id="yoonmanserver2",
            bridge_id="vmbr0",
            static_ip="192.168.2.142",
            prefix=24,
            gateway="192.168.2.1",
            hardware_overrides={"cpu": 8},
        )
        with session_scope() as session:
            general = session.get(CreateVmProfile, "general-vm")
            general.cpu_max = 4

        result = run_preflight(draft, profiles=profile_repository.get_active_create_vm_profiles_by_id(), inventory_adapter=FakeProxmoxInventoryAdapter())

        self.assertIn("profile_cpu_out_of_range", {risk.code for risk in result.risks if risk.level == "red"})


if __name__ == "__main__":
    unittest.main()
