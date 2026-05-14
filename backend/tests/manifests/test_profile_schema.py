"""Tests for the static Create VM profile schema/defaults."""

import unittest


class ProfileSchemaTests(unittest.TestCase):
    def _load_profiles(self):
        try:
            from app.manifests.loader import load_builtin_profiles
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.manifests.loader.load_builtin_profiles for PRD profile "
                f"schema loading, but it is missing: {exc}"
            )
        return {profile.profile_id: profile for profile in load_builtin_profiles()}

    def test_static_create_vm_profiles_are_enabled_and_locked(self):
        profiles = self._load_profiles()
        self.assertEqual({"general-vm", "runtime-server", "development-vm"}, set(profiles))
        expected = {
            "general-vm": {
                "display_name_ko": "범용 VM",
                "cpu": (2, 1, 8),
                "memory_mb": (4096, 1024, 32768),
                "disk_gb": (50, 50, 500),
            },
            "runtime-server": {
                "display_name_ko": "서비스 실행용 VM",
                "cpu": (4, 2, 16),
                "memory_mb": (8192, 4096, 65536),
                "disk_gb": (100, 80, 1000),
            },
            "development-vm": {
                "display_name_ko": "개발/테스트용 VM",
                "cpu": (2, 1, 12),
                "memory_mb": (4096, 2048, 32768),
                "disk_gb": (50, 50, 500),
            },
        }
        for profile_id, hardware in expected.items():
            with self.subTest(profile_id=profile_id):
                profile = profiles[profile_id]
                self.assertTrue(profile.enabled)
                self.assertTrue(profile.create_enabled)
                self.assertEqual(hardware["display_name_ko"], profile.display_name_ko)
                self.assertEqual("yoon", profile.access.cloud_init_user)
                self.assertFalse(profile.access.password_login)
                self.assertEqual("static", profile.default_ip_mode)
                for field, values in hardware.items():
                    if field == "display_name_ko":
                        continue
                    limit = getattr(profile.hardware, field)
                    self.assertEqual(values, (limit.default, limit.min, limit.max))

    def test_profile_api_shape_omits_target_bound_fields(self):
        profiles = self._load_profiles()
        forbidden = {
            "network",
            "network_id",
            "bridge",
            "bridge_id",
            "static_ip",
            "target_node_id",
            "target_node_candidates",
            "storage",
            "storage_id",
            "template_id",
            "template_vmid",
            "template_name",
            "power_policy",
            "profile_version",
        }
        for profile in profiles.values():
            data = profile.to_dict()
            self.assertEqual(profile.profile_id, data["id"])
            self.assertEqual(profile.profile_id, data["profile_id"])
            self.assertEqual("static_seed", data["source"])
            self.assertEqual("read_only", data["management"])
            self.assertTrue(data["template_requirements"]["require_cloud_init"])
            self.assertTrue(data["template_requirements"]["require_qemu_guest_agent"])
            self.assertEqual("yoon", data["access_recommendations"]["default_user"])
            self.assertEqual(set(), forbidden & set(data))
            rendered = repr(data)
            self.assertNotIn("server-net", rendered)


if __name__ == "__main__":
    unittest.main()
