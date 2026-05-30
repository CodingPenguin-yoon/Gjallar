"""RED tests that lock forbidden legacy/MVP-out-of-scope API surface."""

import contextlib
import io
import unittest


FORBIDDEN_ROUTE_PREFIXES = (
    "/api/deploy",
    "/api/provision",
    "/api/instances/terminate",
    "/api/instances/action",
    "/api/instances/resources",
    "/api/llm",
    "/api/tasks",
    "/api/status",
    "/api/logs",
)


class ForbiddenMvpEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = sorted({getattr(route, "path", "") for route in app.routes})

    def test_legacy_destructive_and_llm_routes_are_not_exposed_in_mvp(self):
        offenders = [
            path
            for path in self.paths
            if any(path == prefix or path.startswith(prefix + "/") for prefix in FORBIDDEN_ROUTE_PREFIXES)
        ]
        self.assertEqual(
            [],
            offenders,
            "PRD MVP must not expose deploy/provision destructive lifecycle, "
            f"resource mutation, or LLM routes: {offenders}",
        )

    def test_runtime_target_write_route_is_not_exposed_in_mvp(self):
        offenders = [path for path in self.paths if path.startswith("/api/v1/runtime-targets")]
        self.assertEqual([], offenders, f"Runtime Target write/API is deferred from MVP: {offenders}")

    def test_drs_unsafe_recommendation_aliases_and_broad_shortcuts_are_absent(self):
        forbidden_drs_paths = {
            "/api/v1/drs/recommendations/{recommendation_id}/approve",
            "/api/v1/drs/recommendations/{recommendation_id}/approve-migrate",
            "/api/v1/drs/recommendations/{recommendation_id}/migrate",
            "/api/v1/drs/recommendations/{recommendation_id}/migration",
            "/api/v1/drs/recommendations/{recommendation_id}/live-migrate",
            "/api/v1/drs/recommendations/{recommendation_id}/check-now",
            "/api/v1/drs/live-migrate",
            "/api/v1/drs/migrate",
        }
        offenders = sorted(forbidden_drs_paths & set(self.paths))
        self.assertEqual([], offenders, f"Unsafe DRS recommendation aliases and broad live-migrate shortcuts must stay absent: {offenders}")


if __name__ == "__main__":
    unittest.main()
