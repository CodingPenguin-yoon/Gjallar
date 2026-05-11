"""RED tests for the PRD-locked general-vm profile schema/defaults."""

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

    def test_general_vm_profile_defaults_are_locked(self):
        profiles = self._load_profiles()
        profile = profiles.get("general-vm")
        self.assertIsNotNone(profile, "general-vm profile must exist")
        self.assertEqual(2, profile.hardware.cpu)
        self.assertEqual(4096, profile.hardware.memory_mb)
        self.assertEqual(50, profile.hardware.disk_gb)
        self.assertEqual("yoon", profile.access.cloud_init_user)
        self.assertFalse(profile.access.password_login)
        self.assertEqual("static", profile.network.default_ip_mode)

    def test_future_profiles_are_not_create_enabled(self):
        profiles = self._load_profiles()
        for profile_id in ("runtime-server", "dev-server", "db-server"):
            if profile_id in profiles:
                self.assertFalse(
                    profiles[profile_id].create_enabled,
                    f"{profile_id} is a future profile and must not be create-enabled in MVP",
                )


if __name__ == "__main__":
    unittest.main()
