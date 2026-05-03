import unittest

from fastapi import HTTPException

from app.domains.deploy.router import DeployRequest, _validate_static_network
from app.main import app


class ProvisionRouteCompatibilityTest(unittest.TestCase):
    def test_provision_endpoint_is_registered_next_to_legacy_deploy(self):
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/deploy", paths)
        self.assertIn("/api/provision", paths)

    def test_static_network_validation_rejects_gateway_outside_vm_ip_subnet(self):
        request = DeployRequest(
            template_id="pve1/9000",
            vm_ip="192.168.2.50/24",
            vm_gateway="192.168.3.1",
        )

        with self.assertRaises(HTTPException) as raised:
            _validate_static_network(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("same subnet", raised.exception.detail)


    def test_static_network_validation_rejects_vm_ip_equal_to_gateway(self):
        request = DeployRequest(
            template_id="pve1/9000",
            vm_ip="192.168.2.1/24",
            vm_gateway="192.168.2.1",
        )

        with self.assertRaises(HTTPException) as raised:
            _validate_static_network(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("must not equal", raised.exception.detail)

    def test_static_network_validation_rejects_network_address(self):
        request = DeployRequest(
            template_id="pve1/9000",
            vm_ip="192.168.2.0/24",
            vm_gateway="192.168.2.1",
        )

        with self.assertRaises(HTTPException) as raised:
            _validate_static_network(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("network or broadcast", raised.exception.detail)

    def test_static_network_validation_accepts_gateway_inside_vm_ip_subnet(self):
        request = DeployRequest(
            template_id="pve1/9000",
            vm_ip="192.168.2.50/24",
            vm_gateway="192.168.2.1",
        )

        _validate_static_network(request)


if __name__ == "__main__":
    unittest.main()
