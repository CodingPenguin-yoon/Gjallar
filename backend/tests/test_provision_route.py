import unittest

from app.main import app


class ProvisionRouteCompatibilityTest(unittest.TestCase):
    def test_provision_endpoint_is_registered_next_to_legacy_deploy(self):
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/deploy", paths)
        self.assertIn("/api/provision", paths)


if __name__ == "__main__":
    unittest.main()
