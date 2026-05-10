"""Tests for IaC-backed network policy API."""

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "Test Gjallar",
            "GIT_AUTHOR_EMAIL": "gjallar-test@example.invalid",
            "GIT_COMMITTER_NAME": "Test Gjallar",
            "GIT_COMMITTER_EMAIL": "gjallar-test@example.invalid",
        },
    )
    return completed.stdout.strip()


class ApiV1NetworkPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
            from app.api.v1 import router as api_v1_router
        cls.paths = {getattr(route, "path", "") for route in app.routes}
        cls.api_v1_router = api_v1_router

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.shared_root = Path(self._temp_dir.name) / "nfs"
        self.iac_root = self.shared_root / "IaC"
        (self.iac_root / "manifests" / "networks").mkdir(parents=True)
        _git(self.iac_root, "init")
        (self.iac_root / ".gitignore").write_text("*.tfstate\n", encoding="utf-8")
        _git(self.iac_root, "add", ".")
        _git(self.iac_root, "commit", "-m", "chore: init network policy test")
        self._env = patch.dict("os.environ", {"GJALLAR_SHARED_ROOT": str(self.shared_root)}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._temp_dir.cleanup()

    def test_network_policy_routes_exist_under_api_v1(self):
        self.assertIn("/api/v1/networks/policy", self.paths)

    def test_get_network_policy_combines_discovered_bridges_and_empty_iac_policy(self):
        response = self.api_v1_router.get_network_policy()

        self.assertTrue(response["ok"])
        data = response["data"]
        self.assertEqual(str(self.iac_root.resolve()), data["iac_root"])
        self.assertEqual("manifests/networks/network-profiles.yaml", data["policy_relative_path"])
        self.assertFalse(data["policy_exists"])
        self.assertGreaterEqual(len(data["bridges"]), 1)
        self.assertIn("registered", data["bridges"][0])
        self.assertEqual([], data["side_effects"])
        self.assertEqual("network_policy_read", response["meta"]["mode"])

    def test_put_network_policy_writes_yaml_and_creates_iac_commit(self):
        before = _git(self.iac_root, "rev-parse", "HEAD")
        payload = {
            "policy": {
                "networks": [
                    {
                        "network_id": "server-net",
                        "display_name": "서버망",
                        "description": "general VM service network",
                        "nodes": [
                            {
                                "node_id": "yoonmanserver2",
                                "bridge_id": "vmbr0",
                                "subnet": "192.168.2.0/24",
                                "gateway": "192.168.2.1",
                                "dns": ["192.168.2.1"],
                                "static_ip_ranges": [
                                    {"start": "192.168.2.140", "end": "192.168.2.150"},
                                    {"start": "192.168.2.160", "end": "192.168.2.170"},
                                ],
                            }
                        ],
                    }
                ]
            }
        }

        response = self.api_v1_router.put_network_policy(payload)

        after = _git(self.iac_root, "rev-parse", "HEAD")
        policy_path = self.iac_root / "manifests" / "networks" / "network-profiles.yaml"
        self.assertTrue(response["ok"])
        self.assertNotEqual(before, after)
        self.assertEqual(after, response["data"]["commit_sha"])
        self.assertEqual(["network_policy_written", "iac_git_commit_created"], response["data"]["side_effects"])
        self.assertTrue(policy_path.is_file())
        text = policy_path.read_text(encoding="utf-8")
        self.assertIn("network_id: server-net", text)
        self.assertIn("display_name: 서버망", text)
        self.assertIn("static_ip_ranges:", text)
        self.assertIn("start: 192.168.2.140", text)
        self.assertNotIn("ip_range:", text)
        self.assertEqual("", _git(self.iac_root, "status", "--porcelain"))

    def test_policy_helpers_find_binding_and_static_ip_range(self):
        from app.network_policy import find_network_policy_binding, ip_in_static_ranges, normalize_network_policy

        policy = normalize_network_policy(
            {
                "networks": [
                    {
                        "network_id": "server-net",
                        "nodes": [
                            {
                                "node_id": "yoonmanserver2",
                                "bridge_id": "vmbr0",
                                "ip_range": "192.168.2.1-192.168.2.254",
                                "static_ip_ranges": [{"start": "192.168.2.140", "end": "192.168.2.150"}],
                            }
                        ],
                    }
                ]
            }
        )

        binding = find_network_policy_binding(policy, node_id="yoonmanserver2", bridge_id="vmbr0", network_id="server-net")

        self.assertIsNotNone(binding)
        self.assertEqual([{"start": "192.168.2.140", "end": "192.168.2.150"}], binding["static_ip_ranges"])
        self.assertTrue(ip_in_static_ranges("192.168.2.149", binding["static_ip_ranges"]))
        self.assertFalse(ip_in_static_ranges("192.168.2.1", binding["static_ip_ranges"]))
        self.assertFalse(ip_in_static_ranges("192.168.2.200", binding["static_ip_ranges"]))


if __name__ == "__main__":
    unittest.main()
