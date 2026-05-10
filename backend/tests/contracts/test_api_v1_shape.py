"""RED tests for the PRD-locked /api/v1 public contract."""

import contextlib
import io
import unittest


class ApiV1ShapeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def test_cluster_summary_route_uses_api_v1_prefix(self):
        self.assertIn(
            "/api/v1/cluster/summary",
            self.paths,
            "PRD requires the read-only cluster summary route under /api/v1, "
            "not only the legacy /api surface.",
        )

    def test_inventory_routes_use_api_v1_prefix(self):
        expected_paths = {
            "/api/v1/nodes",
            "/api/v1/vms",
            "/api/v1/vms/{vmid}",
            "/api/v1/profiles",
            "/api/v1/templates",
            "/api/v1/networks",
            "/api/v1/networks/policy",
        }
        missing = sorted(expected_paths - self.paths)
        self.assertEqual([], missing, f"Missing PRD inventory API routes: {missing}")

    def test_api_v1_response_helpers_exist(self):
        try:
            from app.api.v1 import responses
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.api.v1.responses to define the shared success/error "
                f"response envelope, but it is missing: {exc}"
            )
        self.assertTrue(hasattr(responses, "success_response"))
        self.assertTrue(hasattr(responses, "error_response"))


if __name__ == "__main__":
    unittest.main()
