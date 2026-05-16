"""RED tests for Jobs/Risks read API shape required by the MVP screens."""

import contextlib
import io
import unittest


class JobsRisksContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def test_jobs_read_routes_exist_under_api_v1(self):
        expected = {"/api/v1/jobs", "/api/v1/jobs/{job_id}", "/api/v1/jobs/{job_id}/artifacts"}
        missing = sorted(expected - self.paths)
        self.assertEqual([], missing, f"Missing MVP job history/artifact routes: {missing}")

    def test_risks_read_route_exists_under_api_v1(self):
        self.assertIn(
            "/api/v1/risks",
            self.paths,
            "MVP Risks screen must read risk summaries from /api/v1/risks.",
        )

    def test_vm_start_route_exists_without_legacy_instance_action_route(self):
        self.assertIn(
            "/api/v1/nodes/{node_id}/vms/{vmid}/actions/start",
            self.paths,
            "Infra Explorer VM start must use the explicit /api/v1 node/vmid action route.",
        )
        self.assertNotIn("/api/instances/action", self.paths)
        self.assertNotIn("/api/v1/instances/action", self.paths)


if __name__ == "__main__":
    unittest.main()
