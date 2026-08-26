"""RED tests for Jobs/Risks read API shape required by the MVP screens."""

import asyncio
import contextlib
import io
import inspect
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class JobsRisksContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def _run(self, awaitable):
        if inspect.isawaitable(awaitable):
            return asyncio.run(awaitable)
        return awaitable

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

    def test_jobs_and_artifacts_return_stable_503_when_persistence_query_fails(self):
        from app.api.v1 import jobs_compat

        routes = (
            (jobs_compat.list_jobs, (), "JOBS_PERSISTENCE_UNAVAILABLE"),
            (jobs_compat.get_job, ("job-1",), "JOBS_PERSISTENCE_UNAVAILABLE"),
            (jobs_compat.list_job_artifacts, ("job-1",), "JOBS_PERSISTENCE_UNAVAILABLE"),
        )
        with patch.object(
            jobs_compat,
            "list_job_runs_strict",
            side_effect=RuntimeError("secret-bearing database failure"),
        ), patch.object(
            jobs_compat,
            "get_job_run_strict",
            side_effect=RuntimeError("secret-bearing database failure"),
        ):
            for route, args, expected_code in routes:
                with self.subTest(route=route.__name__), self.assertRaises(HTTPException) as raised:
                    self._run(route(*args))
                self.assertEqual(503, raised.exception.status_code)
                self.assertEqual(expected_code, raised.exception.detail["code"])
                self.assertTrue(raised.exception.detail["retryable"])
                self.assertEqual([], raised.exception.detail["side_effects"])
                self.assertNotIn("secret-bearing", str(raised.exception.detail))

    def test_risks_return_stable_503_when_persistence_query_fails(self):
        from app.api.v1 import jobs_compat

        with patch.object(
            jobs_compat,
            "list_job_runs_strict",
            side_effect=RuntimeError("secret-bearing database failure"),
        ):
            with self.assertRaises(HTTPException) as raised:
                self._run(jobs_compat.list_risks())

        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("RISKS_PERSISTENCE_UNAVAILABLE", raised.exception.detail["code"])
        self.assertTrue(raised.exception.detail["retryable"])
        self.assertEqual([], raised.exception.detail["side_effects"])
        self.assertNotIn("secret-bearing", str(raised.exception.detail))

    def test_jobs_and_risks_preserve_normal_empty_success_envelopes(self):
        from app.api.v1 import jobs_compat

        with patch.object(jobs_compat, "list_job_runs_strict", return_value=[]):
            jobs = self._run(jobs_compat.list_jobs())
            risks = self._run(jobs_compat.list_risks())

        self.assertTrue(jobs["ok"])
        self.assertEqual([], jobs["data"])
        self.assertTrue(risks["ok"])
        self.assertEqual([], risks["data"])

    def test_explicit_vm_lifecycle_routes_exist_without_legacy_instance_action_route(self):
        self.assertIn(
            "/api/v1/nodes/{node_id}/vms/{vmid}/actions/start",
            self.paths,
            "Infra Explorer VM start must use the explicit /api/v1 node/vmid action route.",
        )
        self.assertIn(
            "/api/v1/nodes/{node_id}/vms/{vmid}/actions/shutdown",
            self.paths,
            "Workload Cockpit VM shutdown must use the explicit /api/v1 node/vmid action route.",
        )
        self.assertNotIn("/api/instances/action", self.paths)
        self.assertNotIn("/api/v1/instances/action", self.paths)


if __name__ == "__main__":
    unittest.main()
