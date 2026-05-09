"""RED tests for Set 6 /api/v1 create-VM route surface."""

import contextlib
import io
import unittest


class ApiV1VmCreateRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            from app.main import app
        cls.paths = {getattr(route, "path", "") for route in app.routes}

    def test_create_draft_preflight_plan_routes_exist_under_api_v1(self):
        expected = {
            "/api/v1/vm-create/drafts",
            "/api/v1/vm-create/{draft_id}/preflight",
            "/api/v1/vm-create/{draft_id}/plan",
        }
        missing = sorted(expected - self.paths)
        self.assertEqual([], missing, f"Missing Set 6 create-VM API routes: {missing}")


if __name__ == "__main__":
    unittest.main()
